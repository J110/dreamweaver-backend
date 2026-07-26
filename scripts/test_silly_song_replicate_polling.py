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
