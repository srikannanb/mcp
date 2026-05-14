from dataclasses import dataclass, field
from pathlib import Path
import json


@dataclass
class Operation:
    operation_id: str
    summary: str
    description: str
    method: str
    path: str
    parameters: list = field(default_factory=list)


def load_operations(oas_paths: list) -> list:
    """Load and return all non-internal operations from the given OAS files."""
    operations = []
    for path in oas_paths:
        operations.extend(_load_from_file(Path(path)))
    return operations


def _load_from_file(oas_path: Path) -> list:
    with open(oas_path) as f:
        spec = json.load(f)

    inline_params = spec.get("components", {}).get("parameters", {})
    _common_cache = {}

    operations = []
    for path, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            if not isinstance(op, dict):
                continue
            if op.get("x-internal") is True:
                continue

            operation_id = op.get("operationId", "")
            if not operation_id:
                continue

            params = _resolve_parameters(
                op.get("parameters", []), inline_params, oas_path, _common_cache
            )
            operations.append(
                Operation(
                    operation_id=operation_id,
                    summary=op.get("summary", ""),
                    description=op.get("description", ""),
                    method=method.upper(),
                    path=path,
                    parameters=params,
                )
            )

    return operations


def _resolve_parameters(raw_params: list, inline_params: dict, oas_path: Path, cache: dict) -> list:
    resolved = []
    for param in raw_params:
        ref = param.get("$ref", "")
        if not ref:
            resolved.append(param)
            continue

        if ref.startswith("#/"):
            key = ref.split("/")[-1]
            resolved_param = inline_params.get(key)
            if resolved_param:
                resolved.append(resolved_param)
        else:
            file_part, fragment = ref.split("#", 1)
            ref_path = (oas_path.parent / file_part).resolve()
            ref_key = str(ref_path)

            if ref_key not in cache:
                try:
                    with open(ref_path) as f:
                        cache[ref_key] = json.load(f)
                except (OSError, json.JSONDecodeError):
                    continue

            node = cache[ref_key]
            for part in fragment.strip("/").split("/"):
                node = node.get(part, {})
            if node:
                resolved.append(node)

    return resolved
