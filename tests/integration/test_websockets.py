"""Integration tests: WebSocket realtime channels.

Synchronous by design: TestClient runs the app (including the lifespan-started
Redis pub/sub listener) in its own portal thread. Because sync tests do not run
the async autouse truncation fixture, this module truncates with a sync
connection instead (psycopg), keeping tests isolated.
"""

import json
import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import make_url
from starlette.websockets import WebSocketDisconnect
from sqlmodel import SQLModel

from app.main import app

TEST_DSN = (
    make_url(os.environ["DATABASE_URL"])
    .set(drivername="postgresql")
    .render_as_string(hide_password=False)
)


def _truncate_all() -> None:
    tables = ", ".join(f'"{t}"' for t in SQLModel.metadata.tables)
    with psycopg.connect(TEST_DSN, autocommit=True) as conn:
        conn.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")


@pytest.fixture
def ws_client():
    _truncate_all()
    with TestClient(app) as tc:  # __enter__ runs lifespan (Redis listener on)
        yield tc
    _truncate_all()


def _seed(ws_client: TestClient) -> tuple[dict, dict, dict]:
    """Creates alice, an org, and a project through the public API."""
    ws_client.post(
        "/api/v1/auth/register",
        json={
            "email": "ws-alice@example.com",
            "password": "supersecret123",
            "full_name": "WS Alice",
        },
    )
    token = ws_client.post(
        "/api/v1/auth/login",
        data={"username": "ws-alice@example.com", "password": "supersecret123"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    org = ws_client.post(
        "/api/v1/organizations",
        json={"name": "WS Org", "slug": "ws-org"},
        headers=headers,
    ).json()
    project = ws_client.post(
        "/api/v1/organizations/ws-org/projects",
        json={"name": "WS Board"},
        headers=headers,
    ).json()
    return {"token": token}, org, project


def _outsider_token(ws_client: TestClient) -> str:
    ws_client.post(
        "/api/v1/auth/register",
        json={"email": "ws-outsider@example.com", "password": "supersecret123"},
    )
    return ws_client.post(
        "/api/v1/auth/login",
        data={"username": "ws-outsider@example.com", "password": "supersecret123"},
    ).json()["access_token"]


def test_socket_rejects_invalid_token(ws_client):
    _, _, project = _seed(ws_client)
    with pytest.raises((WebSocketDisconnect, RuntimeError)):
        with ws_client.websocket_connect(f"/ws/projects/{project['id']}?token=garbage") as ws:
            ws.receive_json()


def test_socket_rejects_non_members(ws_client):
    _, _, project = _seed(ws_client)
    outsider = _outsider_token(ws_client)
    with pytest.raises((WebSocketDisconnect, RuntimeError)):
        with ws_client.websocket_connect(f"/ws/projects/{project['id']}?token={outsider}") as ws:
            ws.receive_json()


def test_socket_rejects_unknown_project(ws_client):
    alice, _, _ = _seed(ws_client)
    import uuid

    with pytest.raises((WebSocketDisconnect, RuntimeError)):
        with ws_client.websocket_connect(
            f"/ws/projects/{uuid.uuid4()}?token={alice['token']}"
        ) as ws:
            ws.receive_json()


def test_task_created_event_reaches_connected_member(ws_client):
    alice, _, project = _seed(ws_client)

    with ws_client.websocket_connect(
        f"/ws/projects/{project['id']}?token={alice['token']}"
    ) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "connected"
        assert hello["data"]["project_id"] == project["id"]

        r = ws_client.post(
            f"/api/v1/projects/{project['id']}/tasks",
            json={"title": "Realtime task"},
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 201

        event = ws.receive_json()
        assert event["type"] == "task.created"
        assert event["data"]["title"] == "Realtime task"
        assert event["data"]["id"] == r.json()["id"]


def test_client_ping_and_invalid_messages(ws_client):
    alice, _, project = _seed(ws_client)
    with ws_client.websocket_connect(
        f"/ws/projects/{project['id']}?token={alice['token']}"
    ) as ws:
        ws.receive_json()  # connected
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"
        ws.send_text(json.dumps({"type": "mystery"}))
        assert ws.receive_json()["type"] == "error"
        ws.send_text("this is not json")
        assert ws.receive_json()["type"] == "error"
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"
