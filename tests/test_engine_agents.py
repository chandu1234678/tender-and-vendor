from src.engine.agents import run_technical_agent, run_fallback_agent


def test_technical_agent_heuristic(monkeypatch):
    # ensure external model calls are bypassed so heuristic path is exercised
    monkeypatch.setattr("src.engine.agents._call_ollama", lambda *a, **k: None)

    context = "The material can withstand 600C continuously under load."
    requirement = "Must withstand 600C continuously."

    res = run_technical_agent(context, requirement)

    # heuristic should detect numeric evidence and return NEARLY OK
    assert res["status"] == "NEARLY OK"
    assert "citation" in res and res["citation"]


def test_fallback_agent_web_search(monkeypatch):
    # simulate no model response so heuristic path is exercised
    monkeypatch.setattr("src.engine.agents._call_ollama", lambda *a, **k: None)

    context = "Vendor document text with no direct match."
    requirement = "Equivalent spec acceptable alternative"

    res = run_fallback_agent(context, requirement)

    # heuristic should still return a structured response
    assert "status" in res and "confidence" in res
