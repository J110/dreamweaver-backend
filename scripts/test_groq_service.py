from types import SimpleNamespace

from app.services.ai.groq_service import GroqService, RateLimitTracker


class RecordingCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"allowed":true}'))],
            usage=SimpleNamespace(total_tokens=7),
        )


def groq_service():
    service = GroqService.__new__(GroqService)
    completions = RecordingCompletions()
    service.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    service.timeout = GroqService.DEFAULT_TIMEOUT
    service.max_retries = 1
    service.rate_limiter = RateLimitTracker()
    return service, completions


def test_generate_text_preserves_default_request_shape():
    service, completions = groq_service()

    assert service.generate_text("Hello") == '{"allowed":true}'

    assert completions.calls == [{
        "model": GroqService.FAST_MODEL,
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": GroqService.DEFAULT_MAX_TOKENS,
        "temperature": GroqService.DEFAULT_TEMPERATURE,
        "timeout": GroqService.DEFAULT_TIMEOUT,
    }]


def test_generate_text_supports_system_prompt_and_json_object_mode():
    service, completions = groq_service()

    service.generate_text(
        "Classify",
        temperature=0,
        system_prompt="System safety",
        response_format={"type": "json_object"},
    )

    assert completions.calls == [{
        "model": GroqService.FAST_MODEL,
        "messages": [
            {"role": "system", "content": "System safety"},
            {"role": "user", "content": "Classify"},
        ],
        "max_tokens": GroqService.DEFAULT_MAX_TOKENS,
        "temperature": 0,
        "timeout": GroqService.DEFAULT_TIMEOUT,
        "response_format": {"type": "json_object"},
    }]
