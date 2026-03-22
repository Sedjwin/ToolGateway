"""Policy filter evaluation engine."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.models import ToolFilter


@dataclass
class FilterDecision:
    status: str  # pass | denied | modified
    payload: dict[str, Any]
    reason: str | None = None
    filter_type: str | None = None
    filter_name: str | None = None
    transparency_disclosed: bool = False
    evaluator_agent_id: str | None = None
    evaluator_model: str | None = None


def _resolve_target(payload: dict[str, Any], target: str) -> Any:
    """Resolve a target expression against the payload."""
    if target == "*":
        return json.dumps(payload, sort_keys=True)
    if target.startswith("payload."):
        key = target.split(".", 1)[1]
        return payload.get(key)
    return payload.get(target)


def _check_condition(payload: dict[str, Any], condition: dict[str, Any]) -> bool:
    value = _resolve_target(payload, condition.get("target", "*"))
    op = condition.get("operator")
    expected = condition.get("value")
    text_value = "" if value is None else str(value)

    if op == "contains":
        return str(expected) in text_value
    if op == "not_contains":
        return str(expected) not in text_value
    if op == "matches":
        return bool(re.search(str(expected), text_value))
    if op == "equals":
        return value == expected
    if op == "in_list":
        return value in expected if isinstance(expected, list) else False
    if op == "not_in_list":
        return value not in expected if isinstance(expected, list) else False
    if op == "starts_with":
        return text_value.startswith(str(expected))
    if op == "not_starts_with":
        return not text_value.startswith(str(expected))
    if op == "ends_with":
        return text_value.endswith(str(expected))
    if op == "not_ends_with":
        return not text_value.endswith(str(expected))
    return False


def _logical_match(payload: dict[str, Any], config: dict[str, Any]) -> bool:
    """Evaluate AND/OR compound conditions. Empty conditions = always match."""
    conditions = config.get("conditions", [])
    if not conditions:
        return True
    join = str(config.get("join", "AND")).upper()
    results = [_check_condition(payload, c) for c in conditions]
    return any(results) if join == "OR" else all(results)


def _apply_action(payload: dict[str, Any], config: dict[str, Any]) -> tuple[str, dict[str, Any], str | None]:
    action = config.get("action", "pass")
    message = config.get("message")

    if action == "deny":
        return "denied", payload, message or "Request denied by filter"

    if action in {"modify", "redact", "replace", "summarise"}:
        patched = dict(payload)

        if action == "modify":
            for k, v in config.get("patch", {}).items():
                patched[k] = v

        elif action == "summarise":
            for key in config.get("summary_fields", []):
                if key in patched and isinstance(patched[key], str) and len(patched[key]) > 240:
                    patched[key] = patched[key][:240] + " ... [summarised]"

        elif action == "redact":
            for key in config.get("redact_fields", []):
                if key in patched:
                    patched[key] = "[redacted]"

        elif action == "replace":
            replacement = config.get("replacement", {"message": "tool complete, output redacted"})
            patched = replacement if isinstance(replacement, dict) else patched

        return "modified", patched, message

    return "pass", payload, message


async def _evaluate_agent_filter(
    context: dict[str, Any],
    config: dict[str, Any],
) -> tuple[bool, str | None, str | None, str | None]:
    """Call AIGateway evaluator agent. Returns (allowed, reason, agent_id, model)."""
    evaluator_agent_id = config.get("evaluator_agent_id")
    if not evaluator_agent_id:
        return False, "Missing evaluator_agent_id in filter config", None, None

    body = {
        "evaluator_agent_id": evaluator_agent_id,
        "policy_question": config.get("policy_question", "Should this tool call be allowed?"),
        "context": context,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.post(
                f"{settings.aigateway_url}{settings.evaluator_endpoint}", json=body
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        fallback = str(config.get("fallback", "deny")).lower()
        reason = f"Evaluator unavailable: {exc}"
        if fallback == "allow":
            return True, reason, evaluator_agent_id, None
        return False, reason, evaluator_agent_id, None

    decision = str(data.get("decision", "deny")).lower()
    reason = data.get("reason")
    routed_model = data.get("model")
    allowed = decision in {"allow", "approved", "pass"}
    return allowed, reason, evaluator_agent_id, routed_model


def _matches_scope(tool_filter: ToolFilter, principal_type: str, principal_id: str) -> bool:
    if not tool_filter.enabled:
        return False
    if tool_filter.scope == "all":
        return True
    principals = json.loads(tool_filter.principals_json or "[]")
    return f"{principal_type}:{principal_id}" in principals


async def apply_first_matching_filter(
    *,
    filters: list[ToolFilter],
    phase: str,
    payload: dict[str, Any],
    tool_name: str,
    principal_type: str,
    principal_id: str,
    session_id: str | None,
) -> tuple[FilterDecision, int | None]:
    """
    Find the highest-priority filter that applies for this phase and principal.
    Only the first (highest priority = lowest number) matching filter is used.
    Returns (decision, filter_id_or_None).
    """
    candidates = [
        f for f in filters
        if f.phase == phase and _matches_scope(f, principal_type, principal_id)
    ]
    if not candidates:
        return FilterDecision(status="pass", payload=payload), None

    selected = sorted(candidates, key=lambda f: f.priority)[0]
    config = json.loads(selected.config_json or "{}")

    if selected.filter_type == "logical":
        if not _logical_match(payload, config):
            # Conditions not met — filter does not apply to this call
            return FilterDecision(status="pass", payload=payload), None
        status, filtered, reason = _apply_action(payload, config)
        return (
            FilterDecision(
                status=status,
                payload=filtered,
                reason=reason,
                filter_type="logical",
                filter_name=selected.name,
                transparency_disclosed=not selected.transparent,
            ),
            selected.id,
        )

    # Agent-evaluated filter
    context = {
        "tool": tool_name,
        "phase": phase,
        "payload": payload,
        "principal_type": principal_type,
        "principal_id": principal_id,
        "session_id": session_id,
    }
    allowed, reason, evaluator_agent_id, evaluator_model = await _evaluate_agent_filter(context, config)
    if not allowed:
        return (
            FilterDecision(
                status="denied",
                payload=payload,
                reason=reason or "Denied by evaluator",
                filter_type="agent",
                filter_name=selected.name,
                transparency_disclosed=not selected.transparent,
                evaluator_agent_id=evaluator_agent_id,
                evaluator_model=evaluator_model,
            ),
            selected.id,
        )

    return (
        FilterDecision(
            status="pass",
            payload=payload,
            reason=reason,
            filter_type="agent",
            filter_name=selected.name,
            transparency_disclosed=not selected.transparent,
            evaluator_agent_id=evaluator_agent_id,
            evaluator_model=evaluator_model,
        ),
        selected.id,
    )
