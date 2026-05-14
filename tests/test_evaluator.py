import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from eval_mcp.oas_loader import Operation
from eval_mcp.eval_loader import TestCase
from eval_mcp.evaluator import build_tool, evaluate, EvalResult


def make_op(op_id, summary="", description="", params=None):
    return Operation(
        operation_id=op_id,
        summary=summary,
        description=description,
        method="GET",
        path=f"/api/{op_id}",
        parameters=params or [],
    )


def test_build_tool_name_and_description():
    op = make_op("addStarredView", summary="Add Starred View", description="Stars a view.")
    tool = build_tool(op)
    assert tool["name"] == "addStarredView"
    assert "Add Starred View" in tool["description"]
    assert "Stars a view." in tool["description"]


def test_build_tool_summary_only():
    op = make_op("op", summary="Summary only", description="")
    tool = build_tool(op)
    assert tool["description"] == "Summary only"


def test_build_tool_description_only():
    op = make_op("op", summary="", description="Desc only")
    tool = build_tool(op)
    assert tool["description"] == "Desc only"


def test_build_tool_input_schema_has_object_type():
    op = make_op("op", summary="Op")
    tool = build_tool(op)
    assert tool["input_schema"]["type"] == "object"


def test_build_tool_includes_parameter_properties():
    params = [
        {
            "name": "cvId",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
            "description": "View ID",
        }
    ]
    op = make_op("getView", summary="Get View", params=params)
    tool = build_tool(op)
    assert "cvId" in tool["input_schema"]["properties"]
    assert "cvId" in tool["input_schema"]["required"]
    assert tool["input_schema"]["properties"]["cvId"]["description"] == "View ID"


def test_build_tool_handles_list_type_in_schema():
    params = [
        {
            "name": "deptId",
            "in": "query",
            "required": False,
            "schema": {"type": ["string", "null", "integer"]},
        }
    ]
    op = make_op("op", summary="Op", params=params)
    tool = build_tool(op)
    assert tool["input_schema"]["properties"]["deptId"]["type"] == "string"


def _make_mock_async_client(tool_name):
    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.name = tool_name
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client


def test_evaluate_correct_tool_selected():
    ops = [make_op("addStarredView", summary="Add Starred View", description="Stars a view.")]
    cases = [TestCase(prompt="Star a view", expected_operation_id="addStarredView")]

    mock_client = _make_mock_async_client("addStarredView")
    with patch("eval_mcp.evaluator.anthropic.AsyncAnthropic", return_value=mock_client):
        results = evaluate(ops, cases, "claude-sonnet-4-6")

    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].actual == "addStarredView"
    assert results[0].expected == "addStarredView"


def test_evaluate_wrong_tool_selected():
    ops = [
        make_op("addStarredView", summary="Add Starred View", description="Stars a view."),
        make_op("removeStarredView", summary="Remove Starred View", description="Unstars a view."),
    ]
    cases = [TestCase(prompt="Star a view", expected_operation_id="addStarredView")]

    mock_client = _make_mock_async_client("removeStarredView")
    with patch("eval_mcp.evaluator.anthropic.AsyncAnthropic", return_value=mock_client):
        results = evaluate(ops, cases, "claude-sonnet-4-6")

    assert results[0].passed is False
    assert results[0].actual == "removeStarredView"


def test_evaluate_sets_descriptions_on_result():
    ops = [make_op("addStarredView", summary="Sum", description="Desc A")]
    cases = [TestCase(prompt="p", expected_operation_id="addStarredView")]

    mock_client = _make_mock_async_client("addStarredView")
    with patch("eval_mcp.evaluator.anthropic.AsyncAnthropic", return_value=mock_client):
        results = evaluate(ops, cases, "claude-sonnet-4-6")

    assert results[0].expected_description == "Desc A"
    assert results[0].actual_description == "Desc A"


def test_evaluate_calls_api_with_tool_choice_any():
    ops = [make_op("op", summary="S", description="D")]
    cases = [TestCase(prompt="p", expected_operation_id="op")]

    mock_client = _make_mock_async_client("op")
    with patch("eval_mcp.evaluator.anthropic.AsyncAnthropic", return_value=mock_client):
        evaluate(ops, cases, "claude-sonnet-4-6")

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "any"}
    assert call_kwargs["model"] == "claude-sonnet-4-6"


def test_evaluate_marks_tools_for_caching():
    """The last tool in the tools array should carry cache_control."""
    ops = [
        make_op("opA", summary="A", description="aa"),
        make_op("opB", summary="B", description="bb"),
    ]
    cases = [TestCase(prompt="p", expected_operation_id="opA")]

    mock_client = _make_mock_async_client("opA")
    with patch("eval_mcp.evaluator.anthropic.AsyncAnthropic", return_value=mock_client):
        evaluate(ops, cases, "claude-sonnet-4-6")

    sent_tools = mock_client.messages.create.call_args.kwargs["tools"]
    assert sent_tools[-1].get("cache_control") == {"type": "ephemeral"}
    assert "cache_control" not in sent_tools[0]


def test_evaluate_ollama_provider_calls_openai_endpoint():
    """With --provider ollama, the evaluator should call AsyncOpenAI with OpenAI-format tools."""
    ops = [make_op("addStarredView", summary="Add Starred View", description="Stars a view.")]
    cases = [TestCase(prompt="Star a view", expected_operation_id="addStarredView")]

    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "addStarredView"
    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("eval_mcp.evaluator.openai.AsyncOpenAI", return_value=mock_client):
        results = evaluate(ops, cases, "llama3.1:8b", provider="ollama")

    assert results[0].passed is True
    assert results[0].actual == "addStarredView"

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == "required"
    assert call_kwargs["tools"][0]["type"] == "function"
    assert call_kwargs["tools"][0]["function"]["name"] == "addStarredView"


def test_evaluate_unknown_provider_raises():
    ops = [make_op("op")]
    cases = [TestCase(prompt="p", expected_operation_id="op")]
    with pytest.raises(ValueError, match="Unknown provider"):
        evaluate(ops, cases, "some-model", provider="bogus")


def test_evaluate_respects_concurrency_semaphore():
    """With concurrency=2, no more than 2 calls should be in-flight at once."""
    import asyncio

    ops = [make_op("op", summary="S", description="D")]
    cases = [TestCase(prompt=f"p{i}", expected_operation_id="op") for i in range(6)]

    inflight = 0
    peak = 0
    lock = asyncio.Lock()

    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.name = "op"
    mock_response = MagicMock()
    mock_response.content = [mock_block]

    async def fake_create(**kwargs):
        nonlocal inflight, peak
        async with lock:
            inflight += 1
            peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        async with lock:
            inflight -= 1
        return mock_response

    mock_client = MagicMock()
    mock_client.messages.create = fake_create

    with patch("eval_mcp.evaluator.anthropic.AsyncAnthropic", return_value=mock_client):
        evaluate(ops, cases, "claude-sonnet-4-6", concurrency=2)

    assert peak <= 2
