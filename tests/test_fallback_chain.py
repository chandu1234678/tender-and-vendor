from src.engine import agents


def test_run_fallback_agent_uses_web_search_and_grok(monkeypatch):
    monkeypatch.setattr(agents, "_call_ollama", lambda *args, **kwargs: None)
    monkeypatch.setattr(agents, "_collect_web_search_snippets", lambda query, limit=3: "Vendor support page says the equivalent model is acceptable.")

    seen = {}

    def fake_grok(prompt, model_name, temperature):
        seen["prompt"] = prompt
        seen["model_name"] = model_name
        seen["temperature"] = temperature
        return {
            "status": "NEARLY OK",
            "citation": "Grok citation",
            "reasoning": "Grok fallback used",
            "confidence": 0.66,
        }

    monkeypatch.setattr(agents, "_call_grok", fake_grok)

    result = agents.run_fallback_agent("Vendor proposes an alternate model.", "Must support 600C continuously.", model_name="llama3")

    assert result["status"] == "NEARLY OK"
    assert result["citation"] == "Grok citation"
    assert "Web search evidence" in seen["prompt"]
    assert "equivalent model is acceptable" in seen["prompt"]
    assert seen["model_name"] == "grok-2"
    assert seen["temperature"] == 0.1
