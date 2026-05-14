import json
from pathlib import Path
from eval_mcp.eval_loader import load_test_cases, TestCase


def test_loads_test_cases(tmp_path):
    data = {
        "cases": [
            {"prompt": "Star a view for quick access", "expected": "addStarredView"},
            {"prompt": "Record the view I just opened", "expected": "updateRecentView"},
        ]
    }
    f = tmp_path / "eval.json"
    f.write_text(json.dumps(data))

    cases = load_test_cases(f)

    assert len(cases) == 2
    assert cases[0].prompt == "Star a view for quick access"
    assert cases[0].expected_operation_id == "addStarredView"
    assert cases[1].prompt == "Record the view I just opened"
    assert cases[1].expected_operation_id == "updateRecentView"


def test_empty_cases(tmp_path):
    data = {"cases": []}
    f = tmp_path / "eval.json"
    f.write_text(json.dumps(data))
    cases = load_test_cases(f)
    assert cases == []


def test_returns_test_case_instances(tmp_path):
    data = {"cases": [{"prompt": "p", "expected": "op"}]}
    f = tmp_path / "eval.json"
    f.write_text(json.dumps(data))
    cases = load_test_cases(f)
    assert isinstance(cases[0], TestCase)
