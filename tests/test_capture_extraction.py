from igp.capture import extract_candidate_urls, is_media_url, response_targets_shortcode


def test_extract_candidate_urls_handles_escaped_instagram_json_url():
    text = (
        '{"image_versions2":{"candidates":[{"url":"https:\\/\\/instagram.fboi1-1.fna.fbcdn.net\\/v\\/t39.30808-6\\/abc_n.jpg?stp=c0.64.1536.1920a_cp6_dst-jpg_e35_tt6\\u0026_nc_ht=instagram.fboi1-1.fna.fbcdn.net"}]}}'
    )

    urls = extract_candidate_urls(text)

    assert urls == [
        "https://instagram.fboi1-1.fna.fbcdn.net/v/t39.30808-6/abc_n.jpg?stp=c0.64.1536.1920a_cp6_dst-jpg_e35_tt6&_nc_ht=instagram.fboi1-1.fna.fbcdn.net"
    ]


def test_regional_fbcdn_host_is_accepted():
    assert is_media_url("https://scontent-lga3-2.cdninstagram.com/v/t51.2885-15/abc.webp?x=1")
    assert is_media_url("https://instagram.fdel1-3.fna.fbcdn.net/v/t39.30808-6/abc.jpg?x=1")


def test_static_profile_and_junk_urls_rejected():
    assert not is_media_url("https://static.cdninstagram.com/rsrc.php/v3/yx/r/abc.png")
    assert not is_media_url("https://scontent.cdninstagram.com/v/t51.2885-19/profile_pic.jpg")
    assert not is_media_url("https://instagram.fdel1-3.fna.fbcdn.net/v/t39.30808-6/abc.jpg?stp=s150x150")


def test_response_targets_shortcode_requires_shortcode_or_post_markers():
    assert response_targets_shortcode('{"shortcode":"DWj0dQ4moZ8"}', "DWj0dQ4moZ8")
    assert response_targets_shortcode('{"xdt_shortcode_media":{}}', "DWj0dQ4moZ8")
    assert not response_targets_shortcode('{"feed_items":[]}', "DWj0dQ4moZ8")
