"""Tests for chartwatch API routes."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from chartwatch import api, storage
from chartwatch import config as cfg_module


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def client(temp_db):
    cfg = cfg_module.load()
    cfg["storage"]["db_path"] = temp_db
    cfg["server"]["host"] = "127.0.0.1"
    cfg["server"]["port"] = 8056
    cfg["target_window_id"] = None
    cfg["approval"]["auto_approve"] = False
    store = storage.Storage(temp_db)
    mock_scheduler = MagicMock()
    mock_scheduler.trigger_cycle = AsyncMock()
    mock_scheduler.resolve_pending = MagicMock(return_value=False)
    mock_scheduler.min_interval_seconds = MagicMock(return_value=300)
    mock_scheduler.mcp = MagicMock()
    api._state["cfg"] = cfg
    api._state["store"] = store
    api._state["scheduler"] = mock_scheduler
    return TestClient(api.app)


class TestGetWindows:
    def test_get_windows_returns_list(self, client):
        response = client.get("/api/windows")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestConfigEndpoints:
    def test_set_target_window(self, client):
        response = client.post(
            "/api/config/target-window",
            params={"window_id": 123, "title": "Test Window"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["target_window"] == "Test Window"
        assert data["target_window_id"] == 123

    def test_set_interval(self, client):
        response = client.post(
            "/api/config/interval",
            params={"minutes": 10},
        )
        assert response.status_code == 200
        assert response.json()["interval_minutes"] == 10

    def test_set_auto_approve(self, client):
        response = client.post(
            "/api/config/auto-approve",
            params={"enabled": "true"},
        )
        assert response.status_code == 200
        assert response.json()["approval"]["auto_approve"] is True


class TestSchedulerEndpoints:
    def test_scheduler_start_returns_ok(self, client):
        response = client.post("/api/scheduler/start")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_scheduler_stop_returns_ok(self, client):
        response = client.post("/api/scheduler/stop")
        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestHistoryEndpoint:
    def test_get_history_returns_list(self, client):
        response = client.get("/api/history")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestApproveDenyEndpoints:
    def test_approve_returns_ok_false_when_no_pending(self, client):
        response = client.post("/api/approve/999")
        assert response.status_code == 200
        assert response.json()["ok"] is False

    def test_deny_returns_ok_false_when_no_pending(self, client):
        response = client.post("/api/deny/999")
        assert response.status_code == 200
        assert response.json()["ok"] is False


class TestPrerequisitesEndpoint:
    def test_prerequisites_returns_ok(self, client):
        response = client.get("/api/health/prerequisites")
        assert response.status_code == 200
        data = response.json()
        assert "ok" in data
        assert "ctrader" in data
        assert "mcp" in data


class TestMcpAccountsEndpoint:
    def test_accounts_returns_structure(self, client):
        scheduler = api._state["scheduler"]
        scheduler.mcp.get_accounts = AsyncMock(
            return_value=[
                {"id": 48131263, "login": 4262699, "balance": 1000.0, "currency": "EUR", "type": "Hedged", "isOnline": False},
                {"id": 48131264, "login": 4262700, "balance": 500.0, "currency": "USD", "type": "Hedged", "isOnline": True},
            ]
        )
        scheduler.mcp.call = AsyncMock(return_value={"balance": 166.24})
        scheduler.cfg = {"ctrader_mcp": {"account_id": 48131263}}

        response = client.get("/api/mcp/accounts")
        assert response.status_code == 200
        data = response.json()
        assert "accounts" in data
        assert len(data["accounts"]) == 2
        assert data["selectedAccountId"] == 48131263
        assert data["selectedBalance"] == 166.24

    def test_accounts_no_mcp_returns_empty(self, client):
        api._state["scheduler"].mcp = None
        response = client.get("/api/mcp/accounts")
        assert response.status_code == 200
        data = response.json()
        assert data["accounts"] == []
        assert data["selectedAccountId"] is None
        assert data["selectedBalance"] is None
        api._state["scheduler"].mcp = MagicMock()

    def test_accounts_no_selected_balance_when_no_account_id(self, client):
        scheduler = api._state["scheduler"]
        scheduler.mcp.get_accounts = AsyncMock(return_value=[{"id": 1, "login": 100}])
        scheduler.cfg = {"ctrader_mcp": {}}

        response = client.get("/api/mcp/accounts")
        assert response.status_code == 200
        data = response.json()
        assert data["selectedAccountId"] is None
        assert data["selectedBalance"] is None


class TestSetCtraderAccountEndpoint:
    def test_set_account_success(self, client):
        scheduler = api._state["scheduler"]
        response = client.post(
            "/api/config/ctrader-account",
            json={"account_id": 48131264},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ctrader_mcp"]["account_id"] == 48131264
        assert scheduler.mcp.account_id == 48131264
        assert scheduler.cfg["ctrader_mcp"]["account_id"] == 48131264

    def test_set_account_missing_id_returns_400(self, client):
        response = client.post(
            "/api/config/ctrader-account",
            json={},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "account_id required"


class TestIndexRoute:
    def test_index_returns_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")