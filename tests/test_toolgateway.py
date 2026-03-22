from __future__ import annotations

import json
from uuid import uuid4


def _create_echo_tool(client):
    tool_name = f"echo-tool-{uuid4().hex[:8]}"
    resp = client.post(
        "/tools",
        headers={"X-Admin-Key": "test-admin-key"},
        json={
            "name": tool_name,
            "description": "Echo payload",
            "kind": "echo",
            "state": "active",
            "enabled": True,
            "capabilities": ["none"],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_denied_when_agent_not_granted(client):
    tool = _create_echo_tool(client)

    resp = client.post(
        "/execute",
        headers={"X-Service-Key": "test-service-key"},
        json={
            "tool_name": tool["name"],
            "principal_type": "agent",
            "principal_id": "agent-1",
            "payload": {"text": "hello"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert "denied access" in body["reason"].lower()


def test_incoming_filter_applies_first_by_priority(client):
    tool = _create_echo_tool(client)

    grant = client.put(
        f"/tools/{tool['tool_id']}/grants",
        headers={"X-Admin-Key": "test-admin-key"},
        json={"principal_type": "agent", "principal_id": "agent-2", "enabled": True},
    )
    assert grant.status_code == 200, grant.text

    deny_filter = client.post(
        f"/tools/{tool['tool_id']}/filters",
        headers={"X-Admin-Key": "test-admin-key"},
        json={
            "name": "deny-secret",
            "phase": "incoming",
            "priority": 1,
            "scope": "all",
            "filter_type": "logical",
            "transparent": False,
            "config": {
                "conditions": [{"target": "payload.text", "operator": "contains", "value": "secret"}],
                "join": "AND",
                "action": "deny",
                "message": "blocked",
            },
        },
    )
    assert deny_filter.status_code == 201, deny_filter.text

    modify_filter = client.post(
        f"/tools/{tool['tool_id']}/filters",
        headers={"X-Admin-Key": "test-admin-key"},
        json={
            "name": "modify-text",
            "phase": "incoming",
            "priority": 10,
            "scope": "all",
            "filter_type": "logical",
            "transparent": True,
            "config": {
                "conditions": [{"target": "payload.text", "operator": "contains", "value": "secret"}],
                "join": "AND",
                "action": "modify",
                "patch": {"text": "changed"},
            },
        },
    )
    assert modify_filter.status_code == 201, modify_filter.text

    resp = client.post(
        "/execute",
        headers={"X-Service-Key": "test-service-key"},
        json={
            "tool_name": tool["name"],
            "principal_type": "agent",
            "principal_id": "agent-2",
            "payload": {"text": "contains secret"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["reason"] == "blocked"


def test_outgoing_filter_redacts_and_logs_full_boundary(client):
    tool = _create_echo_tool(client)

    grant = client.put(
        f"/tools/{tool['tool_id']}/grants",
        headers={"X-Admin-Key": "test-admin-key"},
        json={"principal_type": "agent", "principal_id": "agent-3", "enabled": True},
    )
    assert grant.status_code == 200

    outgoing_filter = client.post(
        f"/tools/{tool['tool_id']}/filters",
        headers={"X-Admin-Key": "test-admin-key"},
        json={
            "name": "redact-token",
            "phase": "outgoing",
            "priority": 1,
            "scope": "all",
            "filter_type": "logical",
            "transparent": True,
            "config": {
                "conditions": [{"target": "payload.echo", "operator": "contains", "value": "token"}],
                "join": "AND",
                "action": "replace",
                "replacement": {"message": "tool complete, output redacted"},
            },
        },
    )
    assert outgoing_filter.status_code == 201, outgoing_filter.text

    run = client.post(
        "/execute",
        headers={"X-Service-Key": "test-service-key"},
        json={
            "tool_name": tool["name"],
            "principal_type": "agent",
            "principal_id": "agent-3",
            "payload": {"token": "abcd", "text": "hi"},
            "originating_user_id": "u-1",
            "session_id": "s-1",
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "ok"
    assert body["data"] == {"message": "tool complete, output redacted"}

    logs = client.get("/logs/executions", headers={"X-Admin-Key": "test-admin-key"})
    assert logs.status_code == 200
    items = logs.json()
    matched = [item for item in items if item["request_id"] == body["request_id"]]
    assert matched, "expected log entry for executed request_id"
    latest = matched[0]
    assert latest["tool_name"] == tool["name"]
    assert '"token": "abcd"' in latest["incoming_payload_json"]
    assert '"echo"' in latest["raw_tool_response_json"]
    parsed_filtered_response = json.loads(latest["filtered_response_json"])
    assert parsed_filtered_response["data"]["message"] == "tool complete, output redacted"
