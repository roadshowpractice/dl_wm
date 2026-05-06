import asyncio

from igp.capture import CaptureRequest, run_capture


def test_runtime_skips_fallback_when_post_model_found(monkeypatch, tmp_path):
    called = {"fallback": 0}

    async def fake_capture(_):
        return [{"text": "x"}]

    def fake_find(_, __):
        return {"shortcode": "SC", "assets": [{"carousel_index": 1, "media_type": "image", "candidates": {"image_candidates": [{"url": "https://instagram.fna.fbcdn.net/001.jpg"}]}}], "carousel_count": 1}

    async def fake_structured(context, selected, outdir, request, post_model):
        return [{"path": "001.jpg", "status": "ok", "carousel_index": 1}]

    def fake_rank(_):
        called["fallback"] += 1
        return []

    async def fake_download_fallback(context, assets, outdir):
        called["fallback"] += 1
        return []

    class DummyPlay:
        class chromium:
            @staticmethod
            async def launch(**kwargs):
                class B:
                    async def new_context(self):
                        class C:
                            request = None
                        return C()
                    async def close(self):
                        return None
                return B()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("igp.capture.capture_responses", fake_capture)
    monkeypatch.setattr("igp.capture.find_post_model", fake_find)
    monkeypatch.setattr("igp.capture.download_structured_assets", fake_structured)
    monkeypatch.setattr("igp.capture.rank_fallback_assets", fake_rank)
    monkeypatch.setattr("igp.capture.download_fallback_assets", fake_download_fallback)

    req = CaptureRequest("u", "SC", tmp_path / "c.txt", tmp_path / "o", 1, 1)
    asyncio.run(run_capture(req))
    assert called["fallback"] == 0


def test_runtime_uses_fallback_when_no_model_and_allowed(monkeypatch, tmp_path):
    called = {"fallback": 0}

    async def fake_capture(_):
        return [{"text": "x"}]

    async def fake_download_fallback(context, assets, outdir):
        called["fallback"] += 1
        return [{"index": 1, "path": "001.jpg", "status": "ok"}]

    class DummyPlay:
        class chromium:
            @staticmethod
            async def launch(**kwargs):
                class B:
                    async def new_context(self):
                        class C:
                            request = None
                        return C()
                    async def close(self):
                        return None
                return B()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("igp.capture.capture_responses", fake_capture)
    monkeypatch.setattr("igp.capture.find_post_model", lambda *_: None)
    monkeypatch.setattr("igp.capture.rank_fallback_assets", lambda *_: [{"asset": "a", "url": "https://instagram.fna.fbcdn.net/001.jpg", "variants": ["https://instagram.fna.fbcdn.net/001.jpg"]}])
    monkeypatch.setattr("igp.capture.download_fallback_assets", fake_download_fallback)

    req = CaptureRequest("u", "SC", tmp_path / "c.txt", tmp_path / "o", allow_fallback=True)
    asyncio.run(run_capture(req))
    assert called["fallback"] == 1


def test_runtime_no_model_without_fallback_writes_status(monkeypatch, tmp_path):
    async def fake_capture(_):
        return [{"text": "x"}]

    class DummyPlay:
        class chromium:
            @staticmethod
            async def launch(**kwargs):
                class B:
                    async def new_context(self):
                        class C:
                            request = None
                        return C()
                    async def close(self):
                        return None
                return B()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("igp.capture.capture_responses", fake_capture)
    monkeypatch.setattr("igp.capture.find_post_model", lambda *_: None)

    req = CaptureRequest("u", "SC", tmp_path / "c.txt", tmp_path / "o", allow_fallback=False)
    asyncio.run(run_capture(req))
    manifest = (tmp_path / "o" / "manifest.jsonl").read_text()
    assert "no_post_model" in manifest


def test_integration_range_1_1_emits_exactly_one_row(monkeypatch, tmp_path):
    async def fake_capture(_):
        return [{"text": "x"}]

    def fake_find(*_):
        return {"shortcode": "SC", "assets": [{"carousel_index": 1, "media_type": "image", "candidates": {"image_candidates": [{"url": "https://instagram.fna.fbcdn.net/001.jpg"}]}}, {"carousel_index": 2, "media_type": "image", "candidates": {"image_candidates": [{"url": "https://instagram.fna.fbcdn.net/002.jpg"}]}}], "carousel_count": 2}

    async def fake_structured(context, selected, outdir, request, post_model):
        return [{"carousel_index": a["carousel_index"], "path": f'{a["carousel_index"]:03d}.jpg', "status": "ok"} for a in selected]

    class DummyPlay:
        class chromium:
            @staticmethod
            async def launch(**kwargs):
                class B:
                    async def new_context(self):
                        class C:
                            request = None
                        return C()
                    async def close(self):
                        return None
                return B()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("igp.capture.capture_responses", fake_capture)
    monkeypatch.setattr("igp.capture.find_post_model", fake_find)
    monkeypatch.setattr("igp.capture.download_structured_assets", fake_structured)

    req = CaptureRequest("u", "SC", tmp_path / "c.txt", tmp_path / "o", requested_start=1, requested_end=1)
    asyncio.run(run_capture(req))
    rows = (tmp_path / "o" / "manifest.jsonl").read_text().strip().splitlines()
    assert len(rows) == 1
