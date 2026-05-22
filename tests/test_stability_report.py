from eval_mcp.stability import StabilityResult
from eval_mcp.stability_report import render_html


def make_result(prompt, expected, picks, runs, expected_description="", params=None):
    passes = picks.get(expected, 0)
    errors = picks.get("ERROR", 0)
    return StabilityResult(
        prompt=prompt,
        expected=expected,
        expected_description=expected_description,
        runs=runs,
        passes=passes,
        pass_rate=passes / runs if runs else 0.0,
        picks=picks,
        errors=errors,
        extracted_params=params or [],
    )


def test_creates_html_file(tmp_path):
    results = [make_result("p", "op", {"op": 5}, 5)]
    out = tmp_path / "stability.html"
    render_html(results, str(out))
    assert out.exists()


def test_stable_pass_row_renders_with_status(tmp_path):
    results = [make_result("Star a view", "addStarredView", {"addStarredView": 5}, 5)]
    out = tmp_path / "stability.html"
    render_html(results, str(out))
    content = out.read_text()
    assert "STABLE-PASS" in content
    assert "100%" in content
    assert "5/5" in content


def test_stable_fail_row_renders(tmp_path):
    results = [make_result("Star", "addStarredView", {"removeStarredView": 5}, 5)]
    out = tmp_path / "stability.html"
    render_html(results, str(out))
    content = out.read_text()
    assert "STABLE-FAIL" in content
    assert "0%" in content


def test_flaky_row_renders(tmp_path):
    results = [make_result("p", "opA", {"opA": 3, "opB": 2}, 5)]
    out = tmp_path / "stability.html"
    render_html(results, str(out))
    content = out.read_text()
    assert "FLAKY" in content
    assert "60%" in content
    assert "3/5" in content
    # Both picks appear in the histogram
    assert "opA" in content
    assert "opB" in content


def test_summary_shows_aggregate_counts(tmp_path):
    results = [
        make_result("p1", "op", {"op": 5}, 5),                       # stable-pass
        make_result("p2", "op", {"op": 5}, 5),                       # stable-pass
        make_result("p3", "op", {"op": 3, "other": 2}, 5),           # flaky (60%)
        make_result("p4", "op", {"other": 5}, 5),                    # stable-fail
    ]
    out = tmp_path / "stability.html"
    render_html(results, str(out))
    content = out.read_text()
    # mean = (1.0 + 1.0 + 0.6 + 0.0) / 4 = 0.65 = 65%
    assert "65%" in content
    assert "2/4" in content   # stable-pass
    assert ">1<" in content   # flaky count (loose match: number rendered alone in summary)


def test_error_pick_renders_distinct_class(tmp_path):
    results = [make_result("p", "op", {"op": 3, "ERROR": 2}, 5)]
    out = tmp_path / "stability.html"
    render_html(results, str(out))
    content = out.read_text()
    assert "pick-error" in content
    assert "ERROR" in content


def test_passing_params_appear_in_details(tmp_path):
    results = [
        make_result(
            "Star view 42", "addStarredView",
            {"addStarredView": 2}, 2,
            params=[{"cvId": "42"}, {"cvId": "42"}],
        )
    ]
    out = tmp_path / "stability.html"
    render_html(results, str(out))
    content = out.read_text()
    assert "cvId" in content
    assert "42" in content


def test_html_escapes_prompt(tmp_path):
    results = [make_result("<script>alert(1)</script>", "op", {"op": 5}, 5)]
    out = tmp_path / "stability.html"
    render_html(results, str(out))
    content = out.read_text()
    assert "<script>alert" not in content
    assert "&lt;script&gt;" in content


def test_empty_results_renders_zero_summary(tmp_path):
    out = tmp_path / "stability.html"
    render_html([], str(out))
    content = out.read_text()
    assert "0%" in content
    assert "0/0" in content
