import pytest

from scripts import generate_silly_songs_battlecry as generator


class Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_minimax_prediction_survives_poll_read_timeout_without_duplicate_job(
    monkeypatch,
):
    calls = {"post": 0, "get": 0}
    poll_responses = [
        generator.httpx.ReadTimeout("slow poll"),
        Response({"status": "processing"}),
        Response({
            "status": "succeeded",
            "output": "https://replicate.delivery/song.mp3",
        }),
    ]

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **_kwargs):
            calls["post"] += 1
            assert url.endswith("/models/minimax/music-1.5/predictions")
            return Response({
                "id": "prediction-123",
                "urls": {
                    "get": "https://api.replicate.com/v1/predictions/prediction-123",
                },
            })

        def get(self, url, **_kwargs):
            calls["get"] += 1
            assert url.endswith("/predictions/prediction-123")
            response = poll_responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    monkeypatch.setattr(generator.httpx, "Client", Client)
    monkeypatch.setattr(generator.time, "sleep", lambda _seconds: None)

    output = generator._run_minimax_prediction(
        "playful style",
        "[verse]\nBrush, brush!",
        max_polls=4,
    )

    assert output == "https://replicate.delivery/song.mp3"
    assert calls == {"post": 1, "get": 3}


def test_minimax_poll_does_not_request_after_deadline(monkeypatch):
    calls = {"get": 0}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **_kwargs):
            return Response({
                "id": "prediction-123",
                "urls": {
                    "get": "https://api.replicate.com/v1/predictions/prediction-123",
                },
            })

        def get(self, _url, **_kwargs):
            calls["get"] += 1
            return Response({"status": "processing"})

    clock = iter([0, 0, 11])
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    monkeypatch.setattr(generator.httpx, "Client", Client)
    monkeypatch.setattr(generator.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(generator.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError):
        generator._run_minimax_prediction(
            "playful style",
            "[verse]\nBrush, brush!",
            max_polls=1,
            timeout_seconds=10,
        )

    assert calls["get"] == 0


def test_minimax_download_sends_bearer_token_to_replicate_delivery(monkeypatch):
    captured = {}

    def get(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return Response({})

    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    monkeypatch.setattr(generator.httpx, "get", get)

    generator._download_replicate_output(
        "https://files.replicate.delivery/song.mp3",
    )

    assert captured == {
        "url": "https://files.replicate.delivery/song.mp3",
        "headers": {"Authorization": "Bearer test-token"},
    }


def test_minimax_download_rejects_untrusted_output_host(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")

    with pytest.raises(RuntimeError, match="Unexpected Replicate output host"):
        generator._download_replicate_output("https://example.com/song.mp3")
