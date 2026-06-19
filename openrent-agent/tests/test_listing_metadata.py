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
