"""Tests for chartwatch API routes."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestLlmHealthEndpoint:
    def test_ollama_provider_returns_structure(self, client):
        """Verify /api/health/llm returns correct structure for Ollama provider."""
        test_cfg = {
            "provider": "ollama",
            "ollama": {"host": "http://localhost:11434", "model": "qwen3.5:9b"},
            "nvidia": {},
        }
        with patch.object(cfg_module, "load", return_value=test_cfg):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.status = 200
                mock_resp.__enter__ = MagicMock(return_value=mock_resp)
                mock_resp.__exit__ = MagicMock(return_value=None)
                mock_urlopen.return_value = mock_resp
                response = client.get("/api/health/llm")
                assert response.status_code == 200
                data = response.json()
                assert data["provider"] == "ollama"
                assert data["model"] == "qwen3.5:9b"
                assert data["reachable"] is True
                assert data["error"] is None

    def test_ollama_unreachable(self, client):
        """Verify unreachable Ollama is reported correctly."""
        test_cfg = {
            "provider": "ollama",
            "ollama": {"host": "http://localhost:11434", "model": "qwen3.5:9b"},
            "nvidia": {},
        }
        with patch.object(cfg_module, "load", return_value=test_cfg):
            with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("refused")):
                response = client.get("/api/health/llm")
                assert response.status_code == 200
                data = response.json()
                assert data["provider"] == "ollama"
                assert data["reachable"] is False
                assert data["error"] is not None

    def test_nvidia_provider_returns_structure(self, client):
        """Verify /api/health/llm returns correct structure for NVIDIA provider."""
        test_cfg = {
            "provider": "nvidia",
            "ollama": {},
            "nvidia": {
                "host": "http://localhost:11434",
                "model": "thinkingmachines/inkling",
                "api_key": "test-key",
                "base_url": "https://integrate.api.nvidia.com/v1",
            },
            "llm_model": "thinkingmachines/inkling",
        }
        with patch.object(cfg_module, "load", return_value=test_cfg):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.status = 200
                mock_resp.__enter__ = MagicMock(return_value=mock_resp)
                mock_resp.__exit__ = MagicMock(return_value=None)
                mock_urlopen.return_value = mock_resp
                response = client.get("/api/health/llm")
                assert response.status_code == 200
                data = response.json()
                assert data["provider"] == "nvidia"
                assert data["reachable"] is True


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
        # Balance should come from the accounts list for the selected account,
        # NOT from a separate get_balance call that doesn't specify the account.
        assert data["selectedBalance"] == 1000.0
        # get_balance should NOT have been called since we got balance from the list
        scheduler.mcp.call.assert_not_called()

    def test_accounts_fallback_to_get_balance_when_not_in_list(self, client):
        """When the selected account is not in the accounts list, fall back to get_balance."""
        scheduler = api._state["scheduler"]
        scheduler.mcp.get_accounts = AsyncMock(
            return_value=[
                {"id": 48131264, "login": 4262700, "balance": 500.0, "currency": "USD"},
            ]
        )
        scheduler.mcp.call = AsyncMock(return_value={"balance": 166.24})
        scheduler.cfg = {"ctrader_mcp": {"account_id": 999999}}

        response = client.get("/api/mcp/accounts")
        assert response.status_code == 200
        data = response.json()
        assert data["selectedBalance"] == 166.24
        # get_balance should have been called as fallback
        scheduler.mcp.call.assert_called_once_with("get_balance", {})

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