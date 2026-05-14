from pathlib import Path
from eval_mcp.evaluator import EvalResult
from eval_mcp.report import render_html


def make_result(prompt, expected, actual, passed, exp_desc="", act_desc=""):
    return EvalResult(
        prompt=prompt,
        expected=expected,
        actual=actual,
        passed=passed,
        expected_description=exp_desc,
        actual_description=act_desc,
    )


def test_creates_html_file(tmp_path):
    results = [make_result("Star a view", "addStarredView", "addStarredView", True)]
    out = tmp_path / "report.html"
    render_html(results, str(out))
    assert out.exists()


def test_score_line_shows_passed_total_percent(tmp_path):
    results = [
        make_result("p1", "a", "a", True),
        make_result("p2", "b", "a", False),
    ]
    out = tmp_path / "report.html"
    render_html(results, str(out))
    content = out.read_text()
    assert "1 / 2 passed" in content
    assert "50%" in content


def test_pass_result_shows_pass_badge(tmp_path):
    results = [make_result("p", "op", "op", True)]
    out = tmp_path / "report.html"
    render_html(results, str(out))
    assert "PASS" in out.read_text()


def test_fail_result_shows_fail_badge(tmp_path):
    results = [make_result("p", "op", "wrong", False)]
    out = tmp_path / "report.html"
    render_html(results, str(out))
    assert "FAIL" in out.read_text()


def test_html_contains_prompt_and_tool_names(tmp_path):
    results = [make_result("Star a view", "addStarredView", "addStarredView", True)]
    out = tmp_path / "report.html"
    render_html(results, str(out))
    content = out.read_text()
    assert "Star a view" in content
    assert "addStarredView" in content


def test_html_escapes_special_characters(tmp_path):
    results = [make_result('<script>alert(1)</script>', "op", "op", True)]
    out = tmp_path / "report.html"
    render_html(results, str(out))
    content = out.read_text()
    assert "<script>" not in content
    assert "&lt;script&gt;" in content


def test_html_contains_description_details(tmp_path):
    results = [
        make_result("p", "addStarredView", "addStarredView", True,
                    exp_desc="Stars a view.", act_desc="Stars a view.")
    ]
    out = tmp_path / "report.html"
    render_html(results, str(out))
    assert "Stars a view." in out.read_text()


def test_all_pass_score(tmp_path):
    results = [make_result("p", "op", "op", True) for _ in range(5)]
    out = tmp_path / "report.html"
    render_html(results, str(out))
    assert "5 / 5 passed" in out.read_text()
    assert "100%" in out.read_text()
