import json

from igp.capture import find_post_model, parse_capture_args, select_target_assets
from igp.extract import build_post_model


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


def test_parse_capture_args_range_values():
    req = parse_capture_args(["URL", "SC", "cookies.txt", "out", "1", "3"])
    assert req.requested_start == 1
    assert req.requested_end == 3


def test_range_1_1_selects_exactly_one_asset():
    model = build_post_model(_post_with_assets(), "SC")
    selected = select_target_assets(model, 1, 1)
    assert len(selected) == 1
    assert selected[0]["carousel_index"] == 1


def test_range_1_3_selects_exactly_three_assets():
    model = build_post_model(_post_with_assets(), "SC")
    selected = select_target_assets(model, 1, 3)
    assert len(selected) == 3
    assert [a["carousel_index"] for a in selected] == [1, 2, 3]


def test_range_2_2_selects_only_second_asset():
    model = build_post_model(_post_with_assets(), "SC")
    selected = select_target_assets(model, 2, 2)
    assert len(selected) == 1
    assert selected[0]["carousel_index"] == 2


def test_find_post_model_handles_permalink_target_with_carousel_media_and_range():
    payload = {
        "data": {
            "xdt_api__v1__media__shortcode__web_info": {
                "items": [
                    {
                        "shortcode": "UNRELATED",
                        "carousel_media": [
                            {"image_versions2": {"candidates": [{"url": "https://instagram.fna.fbcdn.net/u1.jpg"}]}}
                        ],
                    },
                    {
                        "permalink": "https://www.instagram.com/p/DWj0dQ4moZ8/",
                        "carousel_media": [
                            {"image_versions2": {"candidates": [{"url": "https://instagram.fna.fbcdn.net/1.jpg"}]}},
                            {"video_versions": [{"url": "https://instagram.fna.fbcdn.net/2.mp4"}]},
                            {"image_versions2": {"candidates": [{"url": "https://instagram.fna.fbcdn.net/3.jpg"}]}},
                            {"image_versions2": {"candidates": [{"url": "https://instagram.fna.fbcdn.net/4.jpg"}]}},
                        ],
                    },
                ]
            }
        }
    }
    captured = [{"url": "https://www.instagram.com/p/DWj0dQ4moZ8/", "text": json.dumps(payload)}]
    model = find_post_model(captured, "DWj0dQ4moZ8")
    assert model is not None
    selected = select_target_assets(model, 1, 3)
    assert [a["carousel_index"] for a in selected] == [1, 2, 3]
