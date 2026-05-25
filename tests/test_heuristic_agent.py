from src.evaluator import MultiAgentEvaluator


def test_heuristic_eval_yes_nearly_ok_and_no():
    evaluator = MultiAgentEvaluator()
    evaluator._generate = None

    yes_result = evaluator.evaluate_spec(
        "vendor-1",
        {"company_Requirement": "Must withstand 600C continuously."},
        "The solution complies and meets 600C continuously with warranty support.",
    )
    nearly_result = evaluator.evaluate_spec(
        "vendor-1",
        {"company_Requirement": "Must withstand 600C continuously."},
        "The solution is rated for 600C in controlled conditions.",
    )
    no_result = evaluator.evaluate_spec(
        "vendor-1",
        {"company_Requirement": "Must withstand 600C continuously."},
        "No related specification is mentioned here.",
    )

    assert yes_result.status == "YES"
    assert yes_result.citation
    assert nearly_result.status == "NEARLY OK"
    assert no_result.status == "NO"
