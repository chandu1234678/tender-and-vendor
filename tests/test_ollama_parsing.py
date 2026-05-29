from src.engine.ollama_client import _extract_lmstudio_text


def test_extract_from_lmstudio_output_message():
    payload = {
        "output": [
            {"type": "reasoning", "content": "analysis..."},
            {"type": "message", "content": "{\"status\": \"YES\"}"},
        ]
    }
    assert _extract_lmstudio_text(payload) == '{"status": "YES"}'


def test_extract_from_openai_choices_message():
    payload = {
        "choices": [
            {"message": {"content": "first"}},
            {"message": {"content": "final result"}},
        ]
    }
    assert _extract_lmstudio_text(payload) == "final result"


def test_extract_from_choices_text_field():
    payload = {"choices": [{"text": "hello world"}]}
    assert _extract_lmstudio_text(payload) == "hello world"


def test_fallback_content_key():
    payload = {"content": "simple"}
    assert _extract_lmstudio_text(payload) == "simple"
