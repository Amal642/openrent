import html
import json
import re
from datetime import datetime
from urllib.request import Request, urlopen

from app.utils.logger import logger


def _clean_text(value):
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", html.unescape(str(value))).strip(" \t\r\n,-")
    return cleaned or None


def _first_int(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text or "", re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        try:
            return int(match.group(1).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def _json_ld_documents(content):
    for raw in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        content or "",
        re.IGNORECASE | re.DOTALL,
    ):
        try:
            parsed = json.loads(html.unescape(raw).strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, list):
            yield from parsed
        else:
            yield parsed


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _address_from_json_ld(content):
    for document in _json_ld_documents(content):
        for item in _walk_json(document):
            address = item.get("address")
            if isinstance(address, str):
                cleaned = _clean_text(address)
                if cleaned:
                    return cleaned
            if isinstance(address, dict):
                parts = []
                for value in (
                    address.get("streetAddress"),
                    address.get("addressLocality"),
                    address.get("postalCode"),
                ):
                    cleaned = _clean_text(value)
                    if cleaned and cleaned.lower() not in {
                        part.lower() for part in parts
                    }:
                        parts.append(cleaned)
                if parts:
                    return ", ".join(parts)
    return None


def _text_from_html(content):
    text = re.sub(
        r"</?(?:br|p|div|li|tr|td|th|h[1-6]|dl|dt|dd)[^>]*>",
        "\n",
        content or "",
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)


def _address_from_heading(content, page_title=""):
    heading_match = re.search(
        r"<h1[^>]*>(.*?)</h1>",
        content or "",
        re.IGNORECASE | re.DOTALL,
    )
    heading = _clean_text(
        re.sub(r"<[^>]+>", " ", heading_match.group(1))
        if heading_match
        else None
    )
    if not heading:
        title = _clean_text(page_title)
        heading = title.split(" - To Rent", 1)[0] if title else None
        if heading and " - " in heading:
            heading = heading.split(" - ", 1)[1]
    if not heading:
        return None

    # The sheet's Address column uses the location, not the property type.
    heading = re.sub(
        r"^\s*\d+\s*Bed\s+(?:Flat|House|Maisonette|Bungalow|Studio|Room)\s*,?\s*",
        "",
        heading,
        flags=re.IGNORECASE,
    )
    return _clean_text(heading)


def _landlord_from_html(content):
    match = re.search(
        r"Meet\s+the\s+Landlord.*?<p[^>]*>(.*?)</p>",
        content or "",
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return _clean_text(re.sub(r"<[^>]+>", " ", match.group(1)))


def parse_listing_metadata(content, body_text="", page_title=""):
    if not body_text:
        body_text = _text_from_html(content)

    searchable = "\n".join(
        part
        for part in (html.unescape(content or ""), body_text or "", page_title or "")
        if part
    )

    rent_pcm = _first_int(
        (
            r"Rent\s*PCM.{0,120}?[£\u00a3]\s*([\d,]+)",
            r"[£\u00a3]\s*([\d,]+)\s*(?:pcm|per\s+month)",
            r'"price"\s*:\s*"?([\d,]+)',
        ),
        searchable,
    )
    bedrooms = _first_int(
        (
            r"\b(\d+)\s*(?:bed|bedroom|bedrooms)\b",
            r"Bedrooms?.{0,80}?(\d+)",
            r'"numberOfRooms"\s*:\s*"?(\d+)',
        ),
        searchable,
    )
    bathrooms = _first_int(
        (
            r"\b(\d+)\s*(?:bath|bathroom|bathrooms)\b",
            r"Bathrooms?.{0,80}?(\d+)",
            r'"numberOfBathroomsTotal"\s*:\s*"?(\d+)',
        ),
        searchable,
    )
    max_tenants = _first_int(
        (
            r"Max\s+Tenants?.{0,80}?(\d+)",
            r"Maximum\s+Tenants?.{0,80}?(\d+)",
        ),
        searchable,
    )

    available_match = re.search(
        r"Available\s+From.{0,200}?<td[^>]*>(.*?)</td>",
        content or "",
        re.IGNORECASE | re.DOTALL,
    )
    if not available_match:
        available_match = re.search(
            r"Available\s+From\s*[:\-]?\s*([^\n<]{2,40})",
            body_text or "",
            re.IGNORECASE,
        )
    available_from_raw = _clean_text(available_match.group(1)) if available_match else None
    if not available_from_raw or available_from_raw.lower() == "today":
        available_from = datetime.utcnow()
    else:
        try:
            available_from = datetime.strptime(available_from_raw, "%d %B %Y")
        except (TypeError, ValueError):
            available_from = datetime.utcnow()

    address = _address_from_json_ld(content)
    if not address:
        address = _address_from_heading(content, page_title)
    if not address:
        address_match = re.search(
            r"(?:Address|Property\s+Address)\s*[:\-]?\s*([^\n<]{4,120})",
            body_text or "",
            re.IGNORECASE,
        )
        address = _clean_text(address_match.group(1)) if address_match else None

    landlord_name = _landlord_from_html(content)
    if not landlord_name:
        landlord_match = re.search(
            r"(?:^|\n)\s*(?:Landlord|Advertised\s+by|Listed\s+by)"
            r"\s*[:\-]?\s*([A-Z][A-Za-z .'\-]{1,60}?)(?=\n|$)",
            body_text or "",
            re.IGNORECASE | re.MULTILINE,
        )
        landlord_name = _clean_text(landlord_match.group(1)) if landlord_match else None

    return {
        "rent_pcm": rent_pcm,
        "available_from": available_from,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "max_tenants": max_tenants,
        "address": address,
        "landlord_name": landlord_name,
    }


def fetch_listing_metadata(property_url, timeout=20):
    request = Request(
        property_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/137 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        content = response.read().decode("utf-8", errors="replace")
        final_url = response.geturl()

    title_match = re.search(
        r"<title[^>]*>(.*?)</title>",
        content,
        re.IGNORECASE | re.DOTALL,
    )
    page_title = _clean_text(title_match.group(1)) if title_match else ""
    metadata = parse_listing_metadata(content, page_title=page_title)
    logger.info(
        "LISTING_METADATA_HTTP_FETCHED "
        f"requested_url={property_url} final_url={final_url} "
        f"address_present={bool(metadata.get('address'))} "
        f"landlord_name_present={bool(metadata.get('landlord_name'))} "
        f"bedrooms={metadata.get('bedrooms')} "
        f"bathrooms={metadata.get('bathrooms')} "
        f"rent_pcm={metadata.get('rent_pcm')}"
    )
    return metadata


async def extract_listing_metadata(page):
    content = await page.content()
    try:
        body_text = await page.locator("body").inner_text(timeout=5000)
    except Exception:
        body_text = ""
    try:
        page_title = await page.title()
    except Exception:
        page_title = ""

    metadata = parse_listing_metadata(content, body_text, page_title)

    if not metadata.get("address"):
        for selector in (
            "h1",
            "[data-testid='property-address']",
            ".property-title",
            ".property-address",
        ):
            try:
                value = await page.locator(selector).first.inner_text(timeout=1500)
            except Exception:
                continue
            cleaned = _clean_text(value)
            if cleaned:
                metadata["address"] = cleaned
                break

    if not metadata.get("landlord_name"):
        for selector in (
            'a[href*="/account/view/"]',
            "[data-testid='landlord-name']",
            ".landlord-name",
        ):
            try:
                value = await page.locator(selector).first.inner_text(timeout=1500)
            except Exception:
                continue
            cleaned = _clean_text(value)
            if cleaned and cleaned.lower() not in {"landlord", "view landlord"}:
                metadata["landlord_name"] = cleaned
                break

    logger.info(
        "LISTING_METADATA_EXTRACTED "
        f"url={getattr(page, 'url', '')} "
        f"address_present={bool(metadata.get('address'))} "
        f"landlord_name_present={bool(metadata.get('landlord_name'))} "
        f"bedrooms={metadata.get('bedrooms')} "
        f"bathrooms={metadata.get('bathrooms')} "
        f"rent_pcm={metadata.get('rent_pcm')}"
    )
    return metadata
