from app.openrent.listing_metadata import parse_listing_metadata


def test_parse_listing_metadata_from_json_ld_and_text():
    content = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@type": "Apartment",
          "address": {
            "streetAddress": "10 High Road",
            "addressLocality": "Romford",
            "postalCode": "RM6"
          },
          "numberOfRooms": 2,
          "numberOfBathroomsTotal": 1
        }
        </script>
      </head>
      <body>Rent PCM £1,599</body>
    </html>
    """
    body = """
    Rent PCM £1,599
    2 bedrooms
    1 bathroom
    Max Tenants: 4
    Landlord: Catherine S
    Available From: 25 June 2026
    """

    result = parse_listing_metadata(content, body, "2 bed flat")

    assert result["rent_pcm"] == 1599
    assert result["bedrooms"] == 2
    assert result["bathrooms"] == 1
    assert result["max_tenants"] == 4
    assert result["address"] == "10 High Road, Romford, RM6"
    assert result["landlord_name"] == "Catherine S"
    assert result["available_from"].strftime("%Y-%m-%d") == "2026-06-25"


def test_parse_listing_metadata_keeps_unknown_values_unknown():
    result = parse_listing_metadata("<html><body>Available From Today</body></html>")

    assert result["rent_pcm"] is None
    assert result["bedrooms"] is None
    assert result["bathrooms"] is None
    assert result["address"] is None
    assert result["landlord_name"] is None


def test_parse_current_openrent_listing_layout():
    content = """
    <html>
      <head>
        <title>
          Orpington - 2 Bed Flat, Wood Martyn Court, BR6 -
          To Rent Now for &#xA3;1,700.00 p/m
        </title>
      </head>
      <body>
        <h1>2 Bed Flat, Wood Martyn Court, BR6</h1>
        <span>2 <span>bedrooms</span></span>
        <span>1 <span>bathrooms</span></span>
        <table>
          <tr><td>Rent PCM</td><td>&#xA3;1,700.00</td></tr>
        </table>
        <h2>Meet the Landlord</h2>
        <div><p class="mb-0 text-center fs-body-large-1 fw-medium">Ojes P.</p></div>
      </body>
    </html>
    """

    result = parse_listing_metadata(
        content,
        page_title=(
            "Orpington - 2 Bed Flat, Wood Martyn Court, BR6 "
            "- To Rent Now for £1,700.00 p/m"
        ),
    )

    assert result["address"] == "Wood Martyn Court, BR6"
    assert result["landlord_name"] == "Ojes P."
    assert result["bedrooms"] == 2
    assert result["bathrooms"] == 1
    assert result["rent_pcm"] == 1700


def test_parse_semi_detached_house_address():
    content = """
    <html><head>
      <title>Feltham London - 2 Bed Semi-Detached House,
      Engleheart Drive, TW14 - To Rent Now for £1,800.00 p/m</title>
    </head><body>
      <h1>2 Bed Semi-Detached House, Engleheart Drive, TW14</h1>
      <span>2 bedrooms</span><span>1 bathrooms</span>
      <tr><td>Rent PCM</td><td>£1,800.00</td></tr>
      <h2>Meet the Landlord</h2><div><p>Huma K.</p></div>
    </body></html>
    """

    result = parse_listing_metadata(content)

    assert result["address"] == "Engleheart Drive, TW14"
    assert result["landlord_name"] == "Huma K."
    assert result["bedrooms"] == 2
    assert result["bathrooms"] == 1
    assert result["rent_pcm"] == 1800
