import json
from pathlib import Path
import pytest
from eval_mcp.oas_loader import load_operations, Operation


def make_oas_file(tmp_path, spec_dict, filename="test.json"):
    f = tmp_path / filename
    f.write_text(json.dumps(spec_dict))
    return f


def test_loads_basic_operation(tmp_path):
    spec = {
        "paths": {
            "/api/v1/views/{cvId}/star": {
                "post": {
                    "operationId": "addStarredView",
                    "summary": "Add Starred View",
                    "description": "Stars a view.",
                    "parameters": [],
                }
            }
        }
    }
    f = make_oas_file(tmp_path, spec)
    ops = load_operations([f])
    assert len(ops) == 1
    assert ops[0].operation_id == "addStarredView"
    assert ops[0].method == "POST"
    assert ops[0].path == "/api/v1/views/{cvId}/star"
    assert ops[0].summary == "Add Starred View"
    assert ops[0].description == "Stars a view."


def test_skips_x_internal_true(tmp_path):
    spec = {
        "paths": {
            "/api/v1/internal": {
                "get": {
                    "operationId": "internalOp",
                    "summary": "Internal",
                    "description": "",
                    "x-internal": True,
                    "parameters": [],
                }
            }
        }
    }
    f = make_oas_file(tmp_path, spec)
    ops = load_operations([f])
    assert ops == []


def test_does_not_skip_x_internal_false(tmp_path):
    spec = {
        "paths": {
            "/api/v1/views": {
                "get": {
                    "operationId": "getViews",
                    "summary": "Get Views",
                    "description": "",
                    "x-internal": False,
                    "parameters": [],
                }
            }
        }
    }
    f = make_oas_file(tmp_path, spec)
    ops = load_operations([f])
    assert len(ops) == 1


def test_resolves_inline_ref(tmp_path):
    spec = {
        "components": {
            "parameters": {
                "cvId": {
                    "name": "cvId",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "View ID",
                }
            }
        },
        "paths": {
            "/api/v1/views/{cvId}": {
                "get": {
                    "operationId": "getView",
                    "summary": "Get View",
                    "description": "",
                    "parameters": [{"$ref": "#/components/parameters/cvId"}],
                }
            }
        },
    }
    f = make_oas_file(tmp_path, spec)
    ops = load_operations([f])
    assert len(ops[0].parameters) == 1
    assert ops[0].parameters[0]["name"] == "cvId"


def test_resolves_cross_file_ref(tmp_path):
    common = {
        "components": {
            "parameters": {
                "orgId": {
                    "name": "orgId",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Org ID",
                }
            }
        }
    }
    common_dir = tmp_path / "common"
    common_dir.mkdir()
    (common_dir / "Common.json").write_text(json.dumps(common))

    spec = {
        "paths": {
            "/api/v1/views": {
                "get": {
                    "operationId": "getViews",
                    "summary": "Get Views",
                    "description": "",
                    "parameters": [
                        {"$ref": "../common/Common.json#/components/parameters/orgId"}
                    ],
                }
            }
        }
    }
    support_dir = tmp_path / "support"
    support_dir.mkdir()
    f = support_dir / "test.json"
    f.write_text(json.dumps(spec))

    ops = load_operations([f])
    assert len(ops[0].parameters) == 1
    assert ops[0].parameters[0]["name"] == "orgId"


def test_loads_multiple_files(tmp_path):
    def make_spec(op_id):
        return {
            "paths": {
                f"/api/v1/{op_id}": {
                    "get": {
                        "operationId": op_id,
                        "summary": op_id,
                        "description": "",
                        "parameters": [],
                    }
                }
            }
        }

    f1 = make_oas_file(tmp_path, make_spec("opA"), "a.json")
    f2 = make_oas_file(tmp_path, make_spec("opB"), "b.json")
    ops = load_operations([f1, f2])
    assert len(ops) == 2
    assert {op.operation_id for op in ops} == {"opA", "opB"}


def test_skips_operation_without_operation_id(tmp_path):
    spec = {
        "paths": {
            "/api/v1/views": {
                "get": {
                    "summary": "No ID",
                    "description": "",
                    "parameters": [],
                }
            }
        }
    }
    f = make_oas_file(tmp_path, spec)
    ops = load_operations([f])
    assert ops == []


def test_skips_path_level_parameters(tmp_path):
    """OAS 3.0 allows a top-level 'parameters' key on path items (shared params).
    It's a list, not an operation, and must be skipped."""
    spec = {
        "paths": {
            "/api/v1/views/{cvId}": {
                "parameters": [
                    {"name": "cvId", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "get": {
                    "operationId": "getView",
                    "summary": "Get View",
                    "description": "",
                    "parameters": [],
                }
            }
        }
    }
    f = make_oas_file(tmp_path, spec)
    ops = load_operations([f])
    assert len(ops) == 1
    assert ops[0].operation_id == "getView"
