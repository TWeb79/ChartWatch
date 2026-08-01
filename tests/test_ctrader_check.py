"""Tests for chartwatch ctrader_check module."""

from unittest.mock import MagicMock, patch

import pytest

from chartwatch import ctrader_check


class TestCheckCTraderRunning:
    def test_ctrader_running_returns_true(self):
        with patch("chartwatch.ctrader_check.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = ctrader_check.check_ctrader_running()
            assert result["running"] is True
            assert result["process_name"] == "cTrader"

    def test_ctrader_running_returns_false(self):
        with patch("chartwatch.ctrader_check.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            result = ctrader_check.check_ctrader_running()
            assert result["running"] is False

    def test_ctrader_running_handles_exception(self):
        with patch("chartwatch.ctrader_check.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("pgrep failed")
            result = ctrader_check.check_ctrader_running()
            assert result["running"] is False
            assert "error" in result


class TestCheckMcpAvailable:
    def test_mcp_reachable(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_open = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_resp
        with patch("chartwatch.ctrader_check.urllib.request.urlopen", mock_open):
            result = ctrader_check.check_mcp_available("http://127.0.0.1:9876/mcp/")
            assert result["reachable"] is True
            assert result["status"] == 200

    def test_mcp_unreachable(self):
        with patch("chartwatch.ctrader_check.urllib.request.urlopen") as mock_open:
            mock_open.side_effect = Exception("Connection refused")
            result = ctrader_check.check_mcp_available("http://127.0.0.1:9876/mcp/")
            assert result["reachable"] is False
            assert "error" in result


class TestCheckPrerequisites:
    def test_all_ok(self):
        cfg = {"ctrader_mcp": {"url": "http://127.0.0.1:9876/mcp/"}}
        with patch.object(ctrader_check, "check_ctrader_running", return_value={"running": True}):
            with patch.object(ctrader_check, "check_mcp_available", return_value={"reachable": True}):
                result = ctrader_check.check_prerequisites(cfg)
                assert result["ok"] is True
                assert result["ctrader"]["running"] is True
                assert result["mcp"]["reachable"] is True

    def test_ctrader_not_running(self):
        cfg = {"ctrader_mcp": {"url": "http://127.0.0.1:9876/mcp/"}}
        with patch.object(ctrader_check, "check_ctrader_running", return_value={"running": False}):
            with patch.object(ctrader_check, "check_mcp_available", return_value={"reachable": True}):
                result = ctrader_check.check_prerequisites(cfg)
                assert result["ok"] is False

    def test_mcp_not_reachable(self):
        cfg = {"ctrader_mcp": {"url": "http://127.0.0.1:9876/mcp/"}}
        with patch.object(ctrader_check, "check_ctrader_running", return_value={"running": True}):
            with patch.object(ctrader_check, "check_mcp_available", return_value={"reachable": False}):
                result = ctrader_check.check_prerequisites(cfg)
                assert result["ok"] is False

    def test_no_mcp_url(self):
        cfg = {}
        result = ctrader_check.check_prerequisites(cfg)
        assert result["ok"] is False
        assert result["mcp"]["reachable"] is False