from __future__ import annotations

import json
from typing import Any, Iterable


_SCENE_LIST_CONTRACT_MARKERS = (
    "wrong number of scene allocations",
    "wrong number of scenes",
    "wrong number of scene roles",
    "must align with the planned scene order",
    "must preserve planned scene order",
    "Duplicate dialogue allocation",
    "Duplicate scene character cast",
    "Duplicate story plan scene role",
)


def is_scene_list_contract_violation(error: Exception) -> bool:
    message = str(error)
    return any(marker in message for marker in _SCENE_LIST_CONTRACT_MARKERS)


def build_scene_list_contract_repair_prompt(
    *,
    collection_key: str,
    expected_scene_ids: list[str],
    parsed_payload: dict[str, Any],
    error: Exception,
    require_scene_id_field: bool = True,
    extra_rules: Iterable[str] = (),
) -> str:
    expected_scene_count = len(expected_scene_ids)
    previous_json = json.dumps(parsed_payload, ensure_ascii=False, indent=2)
    scene_id_text = ", ".join(expected_scene_ids)
    rules = [
        "Return only valid JSON.",
        f"Keep the top-level `{collection_key}` array.",
        f"`{collection_key}` must contain exactly {expected_scene_count} objects.",
        f"The scene order must match exactly: {scene_id_text}.",
    ]
    if require_scene_id_field:
        rules.append("Use each expected `scene_id` exactly once and do not invent new scene ids.")
    else:
        rules.append(
            "Do not split one planned scene into multiple objects. Item positions 1..N must correspond to the expected scene order."
        )
    rules.extend(extra_rules)
    rule_block = "\n".join(f"- {rule}" for rule in rules)
    return (
        "The previous JSON violated the structured scene contract.\n"
        f"Validation error: {error}\n"
        "Rewrite the previous JSON so it satisfies the exact scene contract.\n"
        "Hard rules:\n"
        f"{rule_block}\n\n"
        "Previous invalid JSON:\n"
        f"{previous_json}"
    )
