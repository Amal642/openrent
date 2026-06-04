import os
import random
import re

from datetime import (
    datetime,
    timedelta
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.utils.logger import logger

AVAILABILITY_OPTIONS = [
    "Weekday evenings after 6pm and weekends work well for us.",
    "Flexible this week, especially evenings and weekends.",
    "Available most evenings after work and weekends.",
    "Can do weekday evenings or weekends — happy to arrange.",
    "Usually free after 5:30pm on weekdays, and most of the weekend.",
    "Evenings from around 6pm work well, or any time at the weekend.",
    "Free most evenings this week and Saturday mornings.",
    "Weekday evenings after work or weekends suit us best.",
]


async def _save_form_debug(page, tag: str) -> None:
    """Save screenshot + HTML to debug/ on form interaction failure."""
    try:
        os.makedirs("debug", exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        screenshot_path = f"debug/{tag}_{ts}.png"
        html_path = f"debug/{tag}_{ts}.html"
        await page.screenshot(path=screenshot_path, full_page=True)
        html = await page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"Form debug artifacts: {screenshot_path} | {html_path}")
    except Exception as exc:
        logger.warning(f"Could not save form debug artifacts: {exc}")

async def open_listing(page, property_url: str):

    logger.info(f"Opening listing: {property_url}")

    await page.goto(property_url, wait_until="domcontentloaded", timeout=30_000)

async def extract_listing_metadata(page):

    content = await page.content()

    # ---------------- RENT ----------------

    rent_match = re.search(
        r"Rent PCM.*?£([\d,]+)",
        content,
        re.DOTALL
    )

    rent_pcm = None

    if rent_match:

        rent_pcm = int(
            rent_match.group(1)
            .replace(",", "")
        )

    # ---------------- AVAILABLE FROM ----------------

    available_match = re.search(
        r"Available From.*?<td>(.*?)</td>",
        content,
        re.DOTALL
    )

    available_from_raw = None

    if available_match:

        available_from_raw = (
            available_match.group(1)
            .strip()
        )

    if (
        not available_from_raw
        or
        available_from_raw.lower() == "today"
    ):

        available_from = datetime.utcnow()

    else:

        try:

            available_from = datetime.strptime(
                available_from_raw,
                "%d %B %Y"
            )

        except:

            available_from = datetime.utcnow()

    # ---------------- BEDROOMS / TENANTS ----------------

    bedrooms = 1
    max_tenants = None

    bedroom_patterns = (
        r"(\d+)\s*(?:bed|bedroom|bedrooms)\b",
        r"Bedrooms?</span>\s*(?:</[^>]+>\s*)*(\d+)",
        r"Bedrooms?</[^>]*>\s*<[^>]*>\s*(\d+)",
    )

    for pattern in bedroom_patterns:
        bed_match = re.search(
            pattern,
            content,
            re.IGNORECASE | re.DOTALL
        )
        if bed_match:
            bedrooms = int(
                bed_match.group(1)
            )
            break

    tenants_match = re.search(
        r"Max Tenants:</span>\s*(\d+)",
        content,
        re.IGNORECASE
    )

    if tenants_match:
        max_tenants = int(
            tenants_match.group(1)
        )

    return {
        "rent_pcm": rent_pcm,
        "available_from": available_from,
        "bedrooms": bedrooms,
        "max_tenants": max_tenants,
    }

async def detect_form_type(page):

    screening_dropdown = await page.query_selector(
        "#ScreeningInfo_FurnishedStateRequired"
    )

    if screening_dropdown:
        return 2

    return 1

async def _click_radio_label(page, selector: str, field_name: str) -> None:
    """
    OpenRent Type 2 screening uses hidden radio inputs with Bootstrap btn-check
    labels.  The visible/interactable element is the <label>, not the <input>,
    so we locate the input's id then click its matching label.
    """
    try:
        logger.info(f"Clicking label for screening field: {field_name}")
        locator = page.locator(selector)
        input_id = await locator.get_attribute("id")
        if input_id:
            await page.locator(f'label[for="{input_id}"]').click()
        else:
            # Fallback: force-click the input directly
            await locator.click(force=True)
    except Exception as exc:
        logger.warning(f"Screening field {field_name} click failed: {exc}")
        try:
            import os
            from datetime import datetime
            os.makedirs("debug", exist_ok=True)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            await page.screenshot(path=f"debug/form_type_2_failure_{ts}.png", full_page=True)
        except Exception:
            pass
        raise


# Maps normalised ScreeningInfo field name (lowercase, no prefix) → radio value.
# Covers both current and known historical OpenRent field names so renaming
# a field (e.g. OnBenefits → IsDSS) is handled without code changes.
_RADIO_ANSWER_MAP: dict[str, str] = {
    "isstudent":       "false",   # not a student
    "isdss":           "false",   # not on DSS / housing benefit
    "onbenefits":      "false",   # not on benefits (legacy name)
    "haspet":          "false",   # no pets
    "haspets":         "false",   # no pets (legacy plural)
    "issmoker":        "false",   # non-smoker
    "smoker":          "false",   # non-smoker variant
    "hasrighttorent":  "true",    # has right to rent in the UK
    "righttorent":     "true",    # right to rent variant
    "minimumtenancy":  "true",    # willing to commit 12+ months
    "longterm":        "true",    # long-term tenancy
    "employed":        "true",    # is employed
}

# Fallback: match answer from visible question text when field name is unknown.
_QUESTION_KEYWORD_ANSWERS: list[tuple[list[str], str]] = [
    (["student"],                             "false"),
    (["benefit", "dss", "housing benefit"],   "false"),
    (["pet"],                                 "false"),
    (["smok"],                                "false"),
    (["right to rent"],                       "true"),
    (["12 month", "minimum tenancy",
      "longer", "long term"],                 "true"),
]


async def _question_text_for_field(page, field_name: str) -> str:
    """Read the visible question label for a radio group by walking up the DOM."""
    try:
        text: str = await page.evaluate(
            """(fieldName) => {
                const inputs = document.querySelectorAll(
                    `input[name="${fieldName}"]`
                );
                if (!inputs.length) return "";
                let parent = inputs[0].parentElement;
                for (let depth = 0; depth < 6; depth++) {
                    if (!parent) break;
                    // Question labels have no [for] attribute
                    for (const el of parent.querySelectorAll(
                            "label:not([for]), legend, p, strong")) {
                        const t = el.textContent.trim();
                        if (t.length > 3) return t.toLowerCase();
                    }
                    parent = parent.parentElement;
                }
                return "";
            }""",
            field_name,
        )
        return text or ""
    except Exception:
        return ""


def _desired_radio_value(field_key: str, question_text: str) -> str | None:
    value = _RADIO_ANSWER_MAP.get(field_key)
    if value is not None:
        return value
    lower_q = question_text.lower()
    for keywords, answer in _QUESTION_KEYWORD_ANSWERS:
        if any(kw in lower_q for kw in keywords):
            return answer
    return None


async def fill_screening_form(page, metadata):
    """
    Fill OpenRent Form Type 2 screening questions dynamically.

    Discovers radio groups from the DOM at runtime so the form remains
    functional when OpenRent renames fields (e.g. OnBenefits → IsDSS).
    Individual field failures are non-fatal: the form attempts to submit
    with whatever answers were successfully filled.
    """
    # ── Discover radio groups ─────────────────────────────────
    all_field_names: list[str] = await page.evaluate(
        """() => {
            const inputs = document.querySelectorAll(
                'input[type="radio"][name^="ScreeningInfo."]'
            );
            const names = new Set();
            inputs.forEach(i => names.add(i.name));
            return Array.from(names);
        }"""
    )
    logger.info(f"Screening radio fields found: {all_field_names}")

    for field_name in all_field_names:
        field_key = field_name.replace("ScreeningInfo.", "").lower()
        question_text = await _question_text_for_field(page, field_name)
        desired_value = _desired_radio_value(field_key, question_text)

        if desired_value is None:
            logger.warning(
                f"No answer rule for '{field_name}' "
                f"(question: '{question_text}') — skipping"
            )
            continue

        logger.info(
            f"Screening '{field_name}': "
            f"question='{question_text}' → value={desired_value}"
        )
        try:
            await _click_radio_label(
                page,
                f'input[name="{field_name}"][value="{desired_value}"]',
                f"{field_name}={desired_value}",
            )
        except Exception as exc:
            logger.warning(f"Could not answer '{field_name}': {exc}")

    # ── Furnished preference (select) ─────────────────────────
    if await page.query_selector("#ScreeningInfo_FurnishedStateRequired"):
        logger.info("Setting furnished preference: don't mind (2)")
        await page.select_option(
            "#ScreeningInfo_FurnishedStateRequired", value="2"
        )

    # ── Move-in date ──────────────────────────────────────────
    if await page.query_selector("#ScreeningInfo_MustMoveInBy"):
        base = metadata.get("available_from") or datetime.utcnow()
        move_in = base + timedelta(days=14)
        formatted = move_in.strftime("%d %B %Y")
        logger.info(f"Setting move-in date: {formatted}")
        await page.fill("#ScreeningInfo_MustMoveInBy", formatted)

    # ── Combined monthly income ───────────────────────────────
    if await page.query_selector("#ScreeningInfo_CombinedMonthlyIncome"):
        rent = metadata.get("rent_pcm") or 1000
        income = (rent * 30) + 20000
        logger.info(f"Setting combined monthly income: {income}")
        await page.fill("#ScreeningInfo_CombinedMonthlyIncome", str(income))

    # ── Declaration checkbox ──────────────────────────────────
    # Locate by label text rather than a generated element id.
    try:
        declaration_label = page.locator(
            "label",
            has_text=re.compile(r"confirm.*correct|correct.*confirm|declaration", re.I),
        )
        if await declaration_label.count() > 0:
            logger.info("Checking declaration checkbox")
            await declaration_label.first.click()
        else:
            # Fallback: any unchecked checkbox on the form
            checkbox = page.locator('input[type="checkbox"]:not(:checked)').first
            if await checkbox.count() > 0:
                await checkbox.check(force=True)
                logger.info("Checked fallback declaration checkbox")
            else:
                logger.warning("Declaration checkbox not found")
    except Exception as exc:
        logger.warning(f"Declaration checkbox interaction failed: {exc}")

async def get_existing_thread_id(page):

    try:

        banner = page.locator(
            "text=You have already enquired about this property"
        )

        if await banner.count() == 0:
            return None

        message_link = page.locator(
            'a[href^="/messages/"]'
        ).first

        href = await message_link.get_attribute("href")

        if not href:
            return None

        return extract_thread_id(href)

    except Exception as e:

        print("Existing thread detection failed:", e)

        return None

async def get_message_link(page):

    links = await page.query_selector_all("a")

    for link in links:

        href = await link.get_attribute("href")

        if not href:
            continue

        if "/messagelandlord/" in href:
            return href

    return None

async def can_contact_landlord(page):

    message_link = await get_message_link(page)

    return message_link is not None

async def send_initial_message(
    page,
    message_url,
    message_text,
    metadata,
):
    logger.info(f"Opening message page: {message_url}")
    await page.goto(message_url, wait_until="domcontentloaded", timeout=30_000)

    # ── Wait for form — selector-based, no networkidle ────────
    logger.info("Waiting for message form")
    try:
        await page.locator("#Availability").wait_for(
            state="visible", timeout=15_000
        )
    except Exception:
        logger.error("Availability field not visible after 15s")
        await _save_form_debug(page, "availability_field_missing")
        raise Exception("Form did not load: #Availability not visible")

    try:
        await page.locator("#Message").wait_for(
            state="visible", timeout=15_000
        )
    except Exception:
        logger.error("Message textarea not visible after 15s")
        await _save_form_debug(page, "message_field_missing")
        raise Exception("Form did not load: #Message not visible")

    # ── Optional screening form (type 2) ──────────────────────
    form_type = await detect_form_type(page)
    logger.info(f"Form type detected: {form_type}")
    if form_type == 2:
        await fill_screening_form(page, metadata)

    # ── Availability ──────────────────────────────────────────
    logger.info("Filling availability field")
    availability_text = random.choice(AVAILABILITY_OPTIONS)
    await page.locator("#Availability").fill(availability_text)

    # ── Message ───────────────────────────────────────────────
    logger.info("Filling message textarea")
    await page.locator("#Message").fill(message_text)

    # ── Submit ────────────────────────────────────────────────
    logger.info("Submitting Request Viewing form")

    # Try role-based selector first (most reliable)
    submit_btn = page.get_by_role(
        "button", name=re.compile(r"request viewing", re.IGNORECASE)
    )
    if await submit_btn.count() == 0:
        submit_btn = page.get_by_role(
            "button",
            name=re.compile(r"send enquiry|send message|submit", re.IGNORECASE),
        )

    if await submit_btn.count() > 0:
        btn = submit_btn.first
        disabled = await btn.get_attribute("disabled")
        if disabled is not None:
            await _save_form_debug(page, "submit_button_disabled")
            raise Exception("Submit button is disabled")
        await btn.click()
    else:
        # Fallback: scan all submit elements
        fallback = await find_submit_button(page)
        if not fallback:
            await _save_form_debug(page, "submit_button_missing")
            raise Exception("Submit button not found")
        disabled = await fallback.get_attribute("disabled")
        if disabled is not None:
            raise Exception("Submit button is disabled")
        await fallback.click()

    # ── Wait for post-submit navigation ───────────────────────
    # Prefer myenquiries redirect; fall back to messages thread;
    # finally accept any URL change. Never use networkidle.
    final_url = page.url
    try:
        await page.wait_for_url("**/myenquiries**", timeout=15_000)
        final_url = page.url
    except Exception:
        try:
            await page.wait_for_url("**/messages/**", timeout=8_000)
            final_url = page.url
        except Exception:
            # Navigation may have already completed or gone elsewhere
            final_url = page.url

    logger.info(f"Post-submit URL: {final_url}")
    return final_url


async def find_message_textarea(page):
    selectors = [
        'textarea[name*="Message" i]',
        'textarea[id*="Message" i]',
        'textarea[placeholder*="message" i]',
        "form textarea",
        "textarea",
    ]

    for selector in selectors:
        element = await page.query_selector(selector)
        if element:
            return element

    return None


async def find_submit_button(page):
    button_text_markers = [
        "request viewing",
        "send enquiry",
        "send message",
        "message landlord",
        "submit",
        "send",
    ]

    buttons = await page.query_selector_all(
        "button[type='submit'], input[type='submit'], button"
    )

    for button in buttons:
        try:
            text = await button.inner_text()
            if not text:
                text = await button.get_attribute("value") or ""
            text = text.strip().lower()

            print(
                "Found submit candidate:",
                text
            )

            if any(marker in text for marker in button_text_markers):
                return button
        except Exception:
            continue

    return None

def extract_thread_id(url):

    parts = url.strip("/").split("/")

    if not parts:
        return None

    last_part = parts[-1]

    if last_part.isdigit():
        return last_part

    return None

async def safe_fill(
    locator,
    value,
    retries=3
):

    for attempt in range(retries):

        try:

            await locator.fill(value)

            return True

        except Exception:

            if attempt == retries - 1:
                raise

            await locator.page.wait_for_timeout(
                1000
            )

    return False
