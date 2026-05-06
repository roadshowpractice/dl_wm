from igp.capture import _select_structured_assets
from igp.extract import build_post_model, structured_extract


def _post_with_assets(shortcode="SC"):
    return {
        "xdt_api__v1__media__shortcode__web_info": {
            "items": [
                {
                    "code": shortcode,
                    "pk": "media_1",
                    "carousel_media": [
                        {"image_versions2": {"candidates": [{"url": "https://instagram.fna.fbcdn.net/001.jpg", "width": 100, "height": 100}]}, "video_versions": []},
                        {"image_versions2": {"candidates": [{"url": "https://instagram.fna.fbcdn.net/002.jpg", "width": 100, "height": 100}]}, "video_versions": []},
                        {"image_versions2": {"candidates": [{"url": "https://instagram.fna.fbcdn.net/003.jpg", "width": 100, "height": 100}]}, "video_versions": []},
                    ],
                }
            ]
        }
    }


def test_range_1_1_selects_exactly_one_asset():
    model = build_post_model(_post_with_assets(), "SC")
    selected = _select_structured_assets(model, 1, 1)
    assert len(selected) == 1
    assert selected[0]["carousel_index"] == 1


def test_range_1_3_selects_exactly_three_assets():
    model = build_post_model(_post_with_assets(), "SC")
    selected = _select_structured_assets(model, 1, 3)
    assert len(selected) == 3
    assert [a["carousel_index"] for a in selected] == [1, 2, 3]


def test_range_2_2_selects_only_second_asset():
    model = build_post_model(_post_with_assets(), "SC")
    selected = _select_structured_assets(model, 2, 2)
    assert len(selected) == 1
    assert selected[0]["carousel_index"] == 2


def test_structured_extract_ignores_unrelated_clusters_and_thumbnails():
    obj = _post_with_assets("TARGET")
    obj["noise"] = {
        "xdt_api__v1__media__shortcode__web_info": {
            "items": [
                {
                    "code": "OTHER",
                    "carousel_media": [
                        {"image_versions2": {"candidates": [{"url": "https://instagram.fna.fbcdn.net/unrelated.jpg", "width": 100, "height": 100}]}}
                    ],
                }
            ]
        },
        "profile_pic_url": "https://scontent.cdninstagram.com/v/t51.2885-19/profile_pic.jpg",
        "clips_preview": "https://instagram.fna.fbcdn.net/video_first_frame_thumbnail.jpg",
    }
    out = structured_extract(obj, "TARGET")
    assert [u for _, u in out] == [
        "https://instagram.fna.fbcdn.net/001.jpg",
        "https://instagram.fna.fbcdn.net/002.jpg",
        "https://instagram.fna.fbcdn.net/003.jpg",
    ]

