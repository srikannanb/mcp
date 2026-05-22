import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from eval_mcp.oas_loader import Operation
from eval_mcp.eval_loader import TestCase
from eval_mcp.stability import evaluate_stability


def make_op(op_id, summary="", description="", params=None):
    return Operation(
        operation_id=op_id,
        summary=summary,
        description=description,
        method="GET",
        path=f"/api/{op_id}",
        parameters=params or [],
    )


def _block(name, input_dict=None):
    b = MagicMock()
    b.type = "tool_use"
    b.name = name
    b.input = input_dict or {}
    return b


def _scripted_anthropic_client(picks):
    """picks: list of (tool_name, input_dict). Each API call consumes the next one."""
    responses = []
    for name, inp in picks:
        r = MagicMock()
        r.content = [_block(name, inp)]
        responses.append(r)
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=responses)
    return client


def test_stable_pass_yields_pass_rate_one():
    ops = [make_op("addStarredView", summary="Add")]
    cases = [TestCase(prompt="Star a view", expected_operation_id="addStarredView")]

    client = _scripted_anthropic_client([("addStarredView", {})] * 5)
    with patch("eval_mcp.stability.anthropic.AsyncAnthropic", return_value=client):
        results = evaluate_stability(ops, cases, "claude-sonnet-4-6")

    assert results[0].pass_rate == 1.0
    assert results[0].passes == 5
    assert results[0].runs == 5
    assert results[0].picks == {"addStarredView": 5}
    assert results[0].errors == 0


def test_stable_fail_yields_pass_rate_zero():
    ops = [
        make_op("addStarredView", summary="Add"),
        make_op("removeStarredView", summary="Remove"),
    ]
    cases = [TestCase(prompt="Star", expected_operation_id="addStarredView")]

    client = _scripted_anthropic_client([("removeStarredView", {})] * 5)
    with patch("eval_mcp.stability.anthropic.AsyncAnthropic", return_value=client):
        results = evaluate_stability(ops, cases, "claude-sonnet-4-6")

    assert results[0].pass_rate == 0.0
    assert results[0].passes == 0
    assert results[0].picks == {"removeStarredView": 5}


def test_flaky_case_reports_partial_pass_rate_and_histogram():
    ops = [
        make_op("addStarredView", summary="Add"),
        make_op("removeStarredView", summary="Remove"),
    ]
    cases = [TestCase(prompt="Star", expected_operation_id="addStarredView")]

    # 3 right, 2 wrong
    picks = [
        ("addStarredView", {}),
        ("removeStarredView", {}),
        ("addStarredView", {}),
        ("removeStarredView", {}),
        ("addStarredView", {}),
    ]
    client = _scripted_anthropic_client(picks)
    with patch("eval_mcp.stability.anthropic.AsyncAnthropic", return_value=client):
        results = evaluate_stability(ops, cases, "claude-sonnet-4-6")

    assert results[0].pass_rate == 0.6
    assert results[0].passes == 3
    assert results[0].picks == {"addStarredView": 3, "removeStarredView": 2}


def test_runs_flag_controls_call_count():
    ops = [make_op("op")]
    cases = [TestCase(prompt="p", expected_operation_id="op")]

    client = _scripted_anthropic_client([("op", {})] * 3)
    with patch("eval_mcp.stability.anthropic.AsyncAnthropic", return_value=client):
        results = evaluate_stability(ops, cases, "claude-sonnet-4-6", runs=3)

    assert results[0].runs == 3
    assert client.messages.create.call_count == 3


def test_extracted_params_collected_only_from_passing_runs():
    ops = [
        make_op("addStarredView", summary="Add"),
        make_op("other"),
    ]
    cases = [TestCase(prompt="p", expected_operation_id="addStarredView")]

    picks = [
        ("addStarredView", {"cvId": "1"}),
        ("other", {"ignored": True}),
        ("addStarredView", {"cvId": "2"}),
    ]
    client = _scripted_anthropic_client(picks)
    with patch("eval_mcp.stability.anthropic.AsyncAnthropic", return_value=client):
        # concurrency=1 makes per-run ordering deterministic for this assertion.
        results = evaluate_stability(ops, cases, "claude-sonnet-4-6", runs=3, concurrency=1)

    # Order-independent: every passing run must contribute its params, "other" must not.
    assert sorted(p["cvId"] for p in results[0].extracted_params) == ["1", "2"]
    assert all("ignored" not in p for p in results[0].extracted_params)


def test_transient_error_recorded_in_histogram_but_does_not_crash():
    ops = [make_op("op")]
    cases = [TestCase(prompt="p", expected_operation_id="op")]

    ok = MagicMock()
    ok.content = [_block("op", {})]

    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=[ok, Exception("529"), ok, ok, ok])

    with patch("eval_mcp.stability.anthropic.AsyncAnthropic", return_value=client):
        results = evaluate_stability(ops, cases, "claude-sonnet-4-6")

    assert results[0].runs == 5
    assert results[0].passes == 4
    assert results[0].errors == 1
    assert results[0].picks.get("ERROR") == 1
    assert results[0].picks.get("op") == 4


def test_ollama_provider_parses_arguments_per_run():
    ops = [make_op("op")]
    cases = [TestCase(prompt="p", expected_operation_id="op")]

    def make_resp(name, args_json):
        tc = MagicMock()
        tc.function.name = name
        tc.function.arguments = args_json
        msg = MagicMock()
        msg.tool_calls = [tc]
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    responses = [make_resp("op", '{"a": 1}') for _ in range(5)]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=responses)

    with patch("eval_mcp.stability.openai.AsyncOpenAI", return_value=client):
        results = evaluate_stability(ops, cases, "llama3.1:8b", provider="ollama")

    assert results[0].pass_rate == 1.0
    assert results[0].extracted_params == [{"a": 1}] * 5


def test_two_cases_aggregated_independently():
    ops = [
        make_op("opA", summary="A"),
        make_op("opB", summary="B"),
    ]
    cases = [
        TestCase(prompt="a", expected_operation_id="opA"),
        TestCase(prompt="b", expected_operation_id="opB"),
    ]

    # case A: all opA (perfect). case B: all opA (wrong every time).
    picks = [("opA", {})] * 5 + [("opA", {})] * 5
    client = _scripted_anthropic_client(picks)
    with patch("eval_mcp.stability.anthropic.AsyncAnthropic", return_value=client):
        results = evaluate_stability(ops, cases, "claude-sonnet-4-6", concurrency=1)

    assert len(results) == 2
    assert results[0].pass_rate == 1.0
    assert results[1].pass_rate == 0.0
    assert results[1].picks == {"opA": 5}


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        evaluate_stability([], [], "m", provider="bogus")


def test_empty_test_cases_returns_empty_list():
    with patch("eval_mcp.stability.anthropic.AsyncAnthropic") as mock_cls:
        results = evaluate_stability([make_op("op")], [], "claude-sonnet-4-6")
    assert results == []
    # Client should not even be constructed when there's nothing to do.
    mock_cls.assert_not_called()
