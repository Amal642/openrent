from datetime import datetime

from app.jobs import sync_google_sheets


def test_hydrate_missing_metadata_persists_and_refreshes(monkeypatch):
    payload = {
        "export_id": 7,
        "listing_pk": 11,
        "listing_id": "2872199",
        "property_url": "https://www.openrent.co.uk/2872199",
        "landlord_name": None,
        "address": None,
        "bedrooms": None,
        "bathrooms": None,
        "rent_pcm": None,
    }
    metadata = {
        "landlord_name": "Ojes P.",
        "address": "Wood Martyn Court, BR6",
        "bedrooms": 2,
        "bathrooms": 1,
        "rent_pcm": 1700,
        "available_from": datetime(2026, 7, 1),
    }
    saved = {}

    monkeypatch.setattr(
        "app.openrent.listing_metadata.fetch_listing_metadata",
        lambda url, proxy_url=None: metadata,
    )
    monkeypatch.setattr(
        sync_google_sheets,
        "save_listing_metadata",
        lambda listing_pk, values: saved.update(
            {"listing_pk": listing_pk, "metadata": values}
        ),
    )
    monkeypatch.setattr(
        sync_google_sheets,
        "get_sheet_export_payload",
        lambda export_id: {**payload, **metadata},
    )

    result = sync_google_sheets._hydrate_missing_metadata(payload)

    assert saved == {"listing_pk": 11, "metadata": metadata}
    assert result["landlord_name"] == "Ojes P."
    assert result["address"] == "Wood Martyn Court, BR6"
    assert result["bedrooms"] == 2
    assert result["bathrooms"] == 1
    assert result["rent_pcm"] == 1700


def test_hydrate_missing_metadata_uses_account_proxy(monkeypatch):
    payload = {
        "export_id": 8,
        "listing_pk": 12,
        "listing_id": "2936562",
        "property_url": "https://www.openrent.co.uk/2936562",
        "proxy_url": "http://user:password@proxy.example:1234",
        "landlord_name": None,
        "address": None,
        "bedrooms": None,
        "bathrooms": None,
        "rent_pcm": None,
    }
    captured = {}
    metadata = {
        "landlord_name": "Huma K.",
        "address": "Engleheart Drive, TW14",
        "bedrooms": 2,
        "bathrooms": 1,
        "rent_pcm": 1800,
    }

    def fake_fetch(url, proxy_url=None):
        captured.update({"url": url, "proxy_url": proxy_url})
        return metadata

    monkeypatch.setattr(
        "app.openrent.listing_metadata.fetch_listing_metadata",
        fake_fetch,
    )
    monkeypatch.setattr(sync_google_sheets, "save_listing_metadata", lambda *args: True)
    monkeypatch.setattr(
        sync_google_sheets,
        "get_sheet_export_payload",
        lambda export_id: {**payload, **metadata},
    )

    result = sync_google_sheets._hydrate_missing_metadata(payload)

    assert captured["proxy_url"] == payload["proxy_url"]
    assert result["address"] == "Engleheart Drive, TW14"
