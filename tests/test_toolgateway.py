"""Integration tests for ToolGateway V2."""
import json

import pytest
import pytest_asyncio

from app.auth import get_admin_principal, get_principal
from app.main import app
from tests.conftest import mock_admin, mock_agent


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "ToolGateway"
    assert r.json()["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_stats_empty(client):
    app.dependency_overrides[get_admin_principal] = mock_admin
    r = await client.get("/api/stats")
    assert r.status_code == 200
    d = r.json()
    assert d["tools_total"] == 0
    assert d["grants_total"] == 0


@pytest.mark.asyncio
async def test_tools_list_empty(client):
    r = await client.get("/api/tools")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_tool_requires_auth(client):
    r = await client.post("/api/tools", json={"name": "test"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_and_get_tool(client):
    app.dependency_overrides[get_admin_principal] = mock_admin
    body = {
        "name": "email",
        "description": "Send emails",
        "category": "custom_local",
        "kind": "echo",
        "state": "approved",
        "enabled": True,
        "capabilities": ["network_access"],
        "variables": {"allowed_domains": ["example.com"]},
    }
    r = await client.post("/api/tools", json=body)
    assert r.status_code == 201
    tool = r.json()
    assert tool["name"] == "email"
    assert tool["state"] == "approved"
    assert tool["capabilities"] == ["network_access"]
    assert tool["variables"]["allowed_domains"] == ["example.com"]

    # Get it back
    r2 = await client.get(f"/api/tools/{tool['tool_id']}")
    assert r2.status_code == 200
    assert r2.json()["name"] == "email"


@pytest.mark.asyncio
async def test_update_tool_state(client):
    app.dependency_overrides[get_admin_principal] = mock_admin
    r = await client.post("/api/tools", json={"name": "test-tool", "kind": "echo"})
    assert r.status_code == 201
    tid = r.json()["tool_id"]

    r2 = await client.patch(f"/api/tools/{tid}", json={"state": "approved", "enabled": True})
    assert r2.status_code == 200
    assert r2.json()["state"] == "approved"
    assert r2.json()["enabled"] is True


@pytest.mark.asyncio
async def test_tool_duplicate_name_409(client):
    app.dependency_overrides[get_admin_principal] = mock_admin
    await client.post("/api/tools", json={"name": "dupe", "kind": "echo"})
    r = await client.post("/api/tools", json={"name": "dupe", "kind": "echo"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_create_grant_and_execute_echo(client):
    app.dependency_overrides[get_admin_principal] = mock_admin
    app.dependency_overrides[get_principal] = mock_agent

    # Register tool
    r = await client.post("/api/tools", json={
        "name": "pinger", "kind": "echo", "state": "approved", "enabled": True
    })
    tool_id = r.json()["tool_id"]

    # Create grant for agent (principal_id = "42" from mock)
    r = await client.post("/api/grants", json={
        "tool_id": tool_id,
        "principal_type": "agent",
        "principal_id": "42",
        "principal_name": "Test Agent",
    })
    assert r.status_code == 201

    # Execute the tool
    r = await client.post("/api/execute", json={"tool_name": "pinger", "payload": {"msg": "hello"}})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["data"]["echo"]["msg"] == "hello"


@pytest.mark.asyncio
async def test_execute_without_grant_rejected(client):
    app.dependency_overrides[get_admin_principal] = mock_admin
    app.dependency_overrides[get_principal] = mock_agent

    await client.post("/api/tools", json={"name": "secure-tool", "kind": "echo", "state": "approved", "enabled": True})

    r = await client.post("/api/execute", json={"tool_name": "secure-tool", "payload": {}})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert "grant" in r.json()["reason"].lower()


@pytest.mark.asyncio
async def test_execute_disabled_tool_rejected(client):
    app.dependency_overrides[get_admin_principal] = mock_admin
    app.dependency_overrides[get_principal] = mock_agent

    r = await client.post("/api/tools", json={"name": "off-tool", "kind": "echo", "state": "approved", "enabled": False})
    tool_id = r.json()["tool_id"]
    await client.post("/api/grants", json={"tool_id": tool_id, "principal_type": "agent", "principal_id": "42"})

    r = await client.post("/api/execute", json={"tool_name": "off-tool", "payload": {}})
    assert r.json()["status"] == "rejected"
    assert "not active" in r.json()["reason"].lower()


@pytest.mark.asyncio
async def test_logical_filter_deny(client):
    app.dependency_overrides[get_admin_principal] = mock_admin
    app.dependency_overrides[get_principal] = mock_agent

    r = await client.post("/api/tools", json={"name": "filtered-tool", "kind": "echo", "state": "approved", "enabled": True})
    tool_id = r.json()["tool_id"]
    await client.post("/api/grants", json={"tool_id": tool_id, "principal_type": "agent", "principal_id": "42"})

    # Create a filter: deny if destination does NOT end with @allowed.com
    filter_body = {
        "name": "domain-restriction",
        "phase": "incoming",
        "priority": 10,
        "scope": "all",
        "filter_type": "logical",
        "action": "deny",
        "config": {
            "conditions": [{"target": "destination", "operator": "not_ends_with", "value": "@allowed.com"}],
            "join": "AND",
            "action": "deny",
            "message": "Only @allowed.com is permitted",
        },
    }
    r = await client.post(f"/api/tools/{tool_id}/filters", json=filter_body)
    assert r.status_code == 201

    # Execute with a disallowed destination — not_ends_with matches → deny
    r = await client.post("/api/execute", json={"tool_name": "filtered-tool", "payload": {"destination": "bad@evil.com"}})
    assert r.json()["status"] == "rejected"
    assert "allowed.com" in r.json()["reason"]


@pytest.mark.asyncio
async def test_filter_pass_for_allowed_value(client):
    app.dependency_overrides[get_admin_principal] = mock_admin
    app.dependency_overrides[get_principal] = mock_agent

    r = await client.post("/api/tools", json={"name": "pass-tool", "kind": "echo", "state": "approved", "enabled": True})
    tool_id = r.json()["tool_id"]
    await client.post("/api/grants", json={"tool_id": tool_id, "principal_type": "agent", "principal_id": "42"})

    # Filter: deny if destination contains "evil"
    await client.post(f"/api/tools/{tool_id}/filters", json={
        "name": "evil-block", "phase": "incoming", "priority": 10, "scope": "all",
        "filter_type": "logical", "action": "deny",
        "config": {
            "conditions": [{"target": "destination", "operator": "contains", "value": "evil"}],
            "join": "AND", "action": "deny", "message": "evil not allowed",
        },
    })

    # Call with a clean destination — conditions not met, passes through
    r = await client.post("/api/execute", json={"tool_name": "pass-tool", "payload": {"destination": "good@example.com"}})
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_filter_dry_run(client):
    app.dependency_overrides[get_admin_principal] = mock_admin

    r = await client.post("/api/tools", json={"name": "dry-tool", "kind": "echo", "state": "approved", "enabled": True})
    tool_id = r.json()["tool_id"]

    r = await client.post(f"/api/tools/{tool_id}/filters", json={
        "name": "spam-check", "phase": "incoming", "priority": 10, "scope": "all",
        "filter_type": "logical", "action": "deny",
        "config": {"conditions": [{"target": "*", "operator": "contains", "value": "poopoo"}],
                   "join": "AND", "action": "deny", "message": "Profanity not allowed"},
    })
    filter_id = r.json()["id"]

    # Dry run with matching payload
    r = await client.post(f"/api/tools/{tool_id}/filters/{filter_id}/dry-run",
                          json={"payload": {"body": "poopoo is in here"}, "principal_type": "agent", "principal_id": "test"})
    assert r.status_code == 200
    assert r.json()["decision"] == "denied"

    # Dry run with clean payload
    r = await client.post(f"/api/tools/{tool_id}/filters/{filter_id}/dry-run",
                          json={"payload": {"body": "clean message"}, "principal_type": "agent", "principal_id": "test"})
    assert r.json()["decision"] == "pass"


@pytest.mark.asyncio
async def test_version_workflow(client):
    app.dependency_overrides[get_admin_principal] = mock_admin

    r = await client.post("/api/tools", json={"name": "versioned", "kind": "echo", "state": "approved", "enabled": True})
    tool_id = r.json()["tool_id"]

    # Add a version — resets tool to pending_review
    r = await client.post(f"/api/tools/{tool_id}/versions", json={"version": "v1.0.0", "notes": "initial"})
    assert r.status_code == 201
    assert r.json()["state"] == "pending_review"
    version_id = r.json()["id"]

    # Tool should now be pending_review
    t = await client.get(f"/api/tools/{tool_id}")
    assert t.json()["state"] == "pending_review"

    # Approve the version
    r = await client.post(f"/api/tools/{tool_id}/versions/{version_id}/approve")
    assert r.json()["state"] == "approved"
    assert r.json()["reviewed_by"] == "admin"

    # Tool state advances to approved
    t = await client.get(f"/api/tools/{tool_id}")
    assert t.json()["state"] == "approved"


@pytest.mark.asyncio
async def test_install_request_workflow(client):
    app.dependency_overrides[get_admin_principal] = mock_admin
    app.dependency_overrides[get_principal] = mock_agent

    # Agent creates a request
    r = await client.post("/api/requests", json={"proposed_name": "weather-tool", "notes": "need weather data"})
    assert r.status_code == 201
    req_id = r.json()["id"]
    assert r.json()["status"] == "requested"

    # Admin approves
    app.dependency_overrides[get_admin_principal] = mock_admin
    r = await client.post(f"/api/requests/{req_id}/approve", json={"admin_notes": "Approved, installing."})
    assert r.json()["status"] == "approved"
    assert r.json()["resolved_by"] == "admin"


@pytest.mark.asyncio
async def test_execution_logged(client):
    app.dependency_overrides[get_admin_principal] = mock_admin
    app.dependency_overrides[get_principal] = mock_agent

    r = await client.post("/api/tools", json={"name": "logtool", "kind": "echo", "state": "approved", "enabled": True})
    tool_id = r.json()["tool_id"]
    await client.post("/api/grants", json={"tool_id": tool_id, "principal_type": "agent", "principal_id": "42"})

    await client.post("/api/execute", json={"tool_name": "logtool", "payload": {"x": 1}})

    r = await client.get("/api/logs")
    assert r.status_code == 200
    assert len(r.json()) >= 1
    assert r.json()[0]["tool_name"] == "logtool"
    assert r.json()[0]["status"] == "completed"
