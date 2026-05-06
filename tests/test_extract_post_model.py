from igp.extract import build_post_model, parse_requested_img_index, structured_extract, loose_extract_from_text


def _sample(shortcode="DX67XoNFFZd"):
    return {
        "xdt_api__v1__media__shortcode__web_info": {
            "items": [
                {
                    "code": shortcode,
                    "carousel_media_count": 2,
                    "caption": {"text": "hello caption"},
                    "user": {"username": "owner1", "id": "10"},
                    "coauthor_producers": [{"username": "collab1", "id": "20"}],
                    "carousel_media": [
                        {"image_versions2": {"candidates": [{"url": "https://instagram.fna.fbcdn.net/a1.jpg", "width": 100, "height": 100}]}},
                        {"image_versions2": {"candidates": [{"url": "https://instagram.fna.fbcdn.net/a2.jpg", "width": 100, "height": 100}]}}
                    ],
                }
            ]
        }
    }


def test_parse_img_index_from_url():
    assert parse_requested_img_index("https://www.instagram.com/p/X/?img_index=2") == 2


def test_img_index_is_1_based():
    assert parse_requested_img_index("https://www.instagram.com/p/X/?img_index=0") is None


def test_absent_img_index_is_none_select_all():
    assert parse_requested_img_index("https://www.instagram.com/p/X/") is None


def test_structured_carousel_preserves_order():
    model = build_post_model(_sample(), "DX67XoNFFZd")
    assert [a[1] for a in structured_extract(_sample(), "DX67XoNFFZd")] == [
        "https://instagram.fna.fbcdn.net/a1.jpg",
        "https://instagram.fna.fbcdn.net/a2.jpg",
    ]
    assert [a["carousel_index"] for a in model["assets"]] == [1, 2]


def test_img_index_2_selects_second_asset_only():
    model = build_post_model(_sample(), "DX67XoNFFZd")
    selected = [a for a in model["assets"] if a["carousel_index"] == 2]
    assert len(selected) == 1


def test_caption_extraction():
    assert build_post_model(_sample(), "DX67XoNFFZd")["caption"] == "hello caption"


def test_collaborators_extraction():
    collaborators = build_post_model(_sample(), "DX67XoNFFZd")["collaborators"]
    assert collaborators[0]["username"] == "collab1"


def test_fallback_loose_extraction_still_works():
    t = '"https://cdninstagram.com/x.jpg?x=1&y=2"'
    assert loose_extract_from_text(t) == ["https://cdninstagram.com/x.jpg?x=1&y=2"]
