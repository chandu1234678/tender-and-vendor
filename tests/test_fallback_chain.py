from src.engine import agents


def test_run_fallback_agent_heuristic(monkeypatch):
    monkeypatch.setattr(agents, "_call_ollama", lambda *args, **kwargs: None)

    result = agents.run_fallback_agent("Vendor proposes an alternate model.", "Must support 600C continuously.", model_name="llama3")

    assert result["status"] in {"YES", "NO", "NEARLY OK"}
    assert "confidence" in result
