"""State matching for guarded macro replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from mobilerun.macro.state import node_semantic_key


@dataclass(frozen=True)
class StateMatchResult:
    matches: bool
    score: float
    reason: str


def compare_states(
    saved_state: Dict[str, Any],
    current_state: Dict[str, Any],
    threshold: float = 0.85,
) -> StateMatchResult:
    saved_phone = saved_state.get("phone_state") or {}
    current_phone = current_state.get("phone_state") or {}
    for field in ("package", "activity"):
        saved_value = saved_phone.get(field)
        current_value = current_phone.get(field)
        if saved_value and current_value and saved_value != current_value:
            return StateMatchResult(
                False,
                0.0,
                f"{field} mismatch: expected {saved_value!r}, observed {current_value!r}",
            )

    saved_keys = _node_key_set(saved_state)
    current_keys = _node_key_set(current_state)
    if not saved_keys and not current_keys and not saved_phone and not current_phone:
        return StateMatchResult(False, 0.0, "state contains no matchable evidence")

    if saved_keys or current_keys:
        intersection = len(saved_keys & current_keys)
        union = len(saved_keys | current_keys)
        node_score = intersection / union if union else 1.0
    else:
        node_score = 1.0

    stable_saved = _stable_resource_ids(saved_state)
    stable_current = _stable_resource_ids(current_state)
    stable_score = 0.0
    if len(stable_saved) >= 2:
        stable_score = len(stable_saved & stable_current) / len(stable_saved)

    phone_score = _phone_score(saved_state, current_state)
    # Large screens often contain volatile feed/card subtrees. If most stable
    # resource IDs still agree, tolerate those missing dynamic children while
    # keeping the stricter full-node score for small/sparse states.
    if len(stable_saved) >= 10 and stable_score >= 0.75:
        node_score = max(node_score, threshold)
    else:
        node_score = max(node_score, stable_score)
    score = round((node_score * 0.85) + (phone_score * 0.15), 4)

    if score >= threshold:
        return StateMatchResult(True, score, f"state matched with score {score:.2f}")

    return StateMatchResult(
        False,
        score,
        f"state similarity {score:.2f} below threshold {threshold:.2f}",
    )


def _node_key_set(state: Dict[str, Any]) -> set[Tuple[Any, ...]]:
    return {
        node_semantic_key(node)
        for node in state.get("nodes", [])
        if any(part is not None and part != "" for part in node_semantic_key(node))
    }


def _stable_resource_ids(state: Dict[str, Any]) -> set[str]:
    return {
        str(node.get("resource_id"))
        for node in state.get("nodes", [])
        if node.get("resource_id")
    }


def _phone_score(saved_state: Dict[str, Any], current_state: Dict[str, Any]) -> float:
    saved_phone = saved_state.get("phone_state") or {}
    current_phone = current_state.get("phone_state") or {}
    fields = [
        field
        for field in ("package", "activity")
        if saved_phone.get(field) is not None and current_phone.get(field) is not None
    ]
    if not fields:
        return 1.0
    matches = sum(
        1 for field in fields if saved_phone.get(field) == current_phone.get(field)
    )
    return matches / len(fields)
