from app.browser.launcher import _should_block_bandwidth_heavy_request


def test_bandwidth_saver_blocks_media_and_raster_images():
    assert _should_block_bandwidth_heavy_request(
        "media",
        "https://cdn.example.com/video.mp4",
    )
    assert _should_block_bandwidth_heavy_request(
        "image",
        "https://cdn.example.com/listing/photo.webp?width=800",
    )
    assert _should_block_bandwidth_heavy_request(
        "image",
        "https://cdn.example.com/listing/photo.JPG",
    )


def test_bandwidth_saver_allows_page_assets_needed_for_controls():
    assert not _should_block_bandwidth_heavy_request(
        "image",
        "https://www.openrent.co.uk/assets/icon.svg",
    )
    assert not _should_block_bandwidth_heavy_request(
        "image",
        "https://www.openrent.co.uk/favicon.ico",
    )
    assert not _should_block_bandwidth_heavy_request(
        "script",
        "https://www.openrent.co.uk/assets/app.js",
    )
    assert not _should_block_bandwidth_heavy_request(
        "stylesheet",
        "https://www.openrent.co.uk/assets/app.css",
    )
