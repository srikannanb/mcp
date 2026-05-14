from dataclasses import dataclass
from pathlib import Path
import json


@dataclass
class TestCase:
    prompt: str
    expected_operation_id: str


def load_test_cases(eval_path: Path) -> list:
    with open(eval_path) as f:
        data = json.load(f)
    return [
        TestCase(
            prompt=case["prompt"],
            expected_operation_id=case["expected"],
        )
        for case in data.get("cases", [])
    ]
