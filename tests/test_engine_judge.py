from src.engine.judge import run_consensus_judge


def test_heuristic_judge_chooses_best():
    technical = {"status": "YES", "confidence": 0.4, "citation": "t", "reasoning": "tech"}
    risk = {"status": "NEARLY OK", "confidence": 0.9, "citation": "r", "reasoning": "risk"}
    fallback = {"status": "NO", "confidence": 0.2, "citation": "f", "reasoning": "fallback"}

    # should fall back to heuristic judge when model call fails (no ollama available)
    res = run_consensus_judge(technical, risk, fallback)

    # deterministic rule prefers NEARLY OK when only one agent is YES
    assert res["status"].startswith("NEARLY")
    assert "confidence" in res
