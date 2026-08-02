"""Tests for chartwatch service modules."""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from chartwatch import decision, guardrails, storage
from chartwatch.scheduler import Scheduler


class TestDecisionValidate:
    def test_valid_decision_passes(self):
        d = {
            "assessment": "Price is trending up",
            "trend_10min": "up",
            "confidence": 0.85,
            "open_position_action": "hold",
            "new_trade": None,
        }
        result = decision.validate(d)
        assert result == d

    def test_missing_required_field_raises(self):
        d = {
            "assessment": "Price is trending up",
            "trend_10min": "up",
        }
        with pytest.raises(decision.InvalidDecision):
            decision.validate(d)

    def test_invalid_trend_raises(self):
        d = {
            "assessment": "test",
            "trend_10min": "invalid",
            "confidence": 0.5,
        }
        with pytest.raises(decision.InvalidDecision):
            decision.validate(d)

    def test_confidence_out_of_range_raises(self):
        d = {
            "assessment": "test",
            "trend_10min": "up",
            "confidence": 1.5,
        }
        with pytest.raises(decision.InvalidDecision):
            decision.validate(d)

    def test_invalid_position_action_raises(self):
        d = {
            "assessment": "test",
            "trend_10min": "up",
            "confidence": 0.5,
            "open_position_action": "invalid",
        }
        with pytest.raises(decision.InvalidDecision):
            decision.validate(d)

    def test_new_trade_missing_fields_raises(self):
        d = {
            "assessment": "test",
            "trend_10min": "up",
            "confidence": 0.5,
            "new_trade": {"direction": "buy", "sl": 100},
        }
        with pytest.raises(decision.InvalidDecision):
            decision.validate(d)

    def test_new_trade_invalid_direction_raises(self):
        d = {
            "assessment": "test",
            "trend_10min": "up",
            "confidence": 0.5,
            "new_trade": {"direction": "invalid", "sl": 100, "tp": 110},
        }
        with pytest.raises(decision.InvalidDecision):
            decision.validate(d)

    def test_new_trade_non_numeric_sl_tp_raises(self):
        d = {
            "assessment": "test",
            "trend_10min": "up",
            "confidence": 0.5,
            "new_trade": {"direction": "buy", "sl": "bad", "tp": 110},
        }
        with pytest.raises(decision.InvalidDecision):
            decision.validate(d)


class TestGuardrailsCheck:
    def test_no_rejection_when_within_limits(self):
        guardrails.check(
            {"new_trade": {"direction": "buy", "sl": 100, "tp": 110}},
            current_price=105,
            open_positions_count=0,
            daily_pnl_pct=0.0,
            limits={"max_daily_loss_pct": 3, "max_concurrent_positions": 1, "min_sl_distance_pips": 10},
            pip_size=0.0001,
        )

    def test_daily_loss_limit_rejected(self):
        with pytest.raises(guardrails.GuardrailRejection):
            guardrails.check(
                {"new_trade": {"direction": "buy", "sl": 100, "tp": 110}},
                current_price=105,
                open_positions_count=0,
                daily_pnl_pct=-5.0,
                limits={"max_daily_loss_pct": 3, "max_concurrent_positions": 1, "min_sl_distance_pips": 10},
                pip_size=0.0001,
            )

    def test_max_concurrent_positions_rejected(self):
        with pytest.raises(guardrails.GuardrailRejection):
            guardrails.check(
                {"new_trade": {"direction": "buy", "sl": 100, "tp": 110}},
                current_price=105,
                open_positions_count=2,
                daily_pnl_pct=0.0,
                limits={"max_daily_loss_pct": 3, "max_concurrent_positions": 1, "min_sl_distance_pips": 10},
                pip_size=0.0001,
            )

    def test_sl_too_close_rejected(self):
        with pytest.raises(guardrails.GuardrailRejection):
            guardrails.check(
                {"new_trade": {"direction": "buy", "sl": 104.9995, "tp": 110}},
                current_price=105,
                open_positions_count=0,
                daily_pnl_pct=0.0,
                limits={"max_daily_loss_pct": 3, "max_concurrent_positions": 1, "min_sl_distance_pips": 10},
                pip_size=0.0001,
            )

    def test_buy_sl_above_tp_rejected(self):
        with pytest.raises(guardrails.GuardrailRejection):
            guardrails.check(
                {"new_trade": {"direction": "buy", "sl": 110, "tp": 100}},
                current_price=105,
                open_positions_count=0,
                daily_pnl_pct=0.0,
                limits={"max_daily_loss_pct": 3, "max_concurrent_positions": 1, "min_sl_distance_pips": 10},
                pip_size=0.0001,
            )

    def test_sell_sl_below_tp_rejected(self):
        with pytest.raises(guardrails.GuardrailRejection):
            guardrails.check(
                {"new_trade": {"direction": "sell", "sl": 90, "tp": 100}},
                current_price=105,
                open_positions_count=0,
                daily_pnl_pct=0.0,
                limits={"max_daily_loss_pct": 3, "max_concurrent_positions": 1, "min_sl_distance_pips": 10},
                pip_size=0.0001,
            )

    def test_no_new_trade_skips_trade_checks(self):
        guardrails.check(
            {"open_position_action": "hold", "new_trade": None},
            current_price=None,
            open_positions_count=0,
            daily_pnl_pct=0.0,
            limits={"max_daily_loss_pct": 3, "max_concurrent_positions": 1, "min_sl_distance_pips": 10},
            pip_size=0.0001,
        )


class TestStorage:
    def test_new_cycle_returns_id(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            s = storage.Storage(db_path)
            cycle_id = s.new_cycle("/tmp/test.png")
            assert isinstance(cycle_id, int)
            assert cycle_id > 0
        finally:
            os.unlink(db_path)

    def test_set_and_get_model_response(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            s = storage.Storage(db_path)
            cycle_id = s.new_cycle("/tmp/test.png")
            response = {"assessment": "test", "trend_10min": "up", "confidence": 0.5}
            s.set_model_response(cycle_id, response)
            rows = s.recent(limit=1)
            assert rows[0]["model_response"] is not None
            parsed = json.loads(rows[0]["model_response"])
            assert parsed["assessment"] == "test"
        finally:
            os.unlink(db_path)

    def test_set_action(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            s = storage.Storage(db_path)
            cycle_id = s.new_cycle("/tmp/test.png")
            s.set_action(cycle_id, "executed")
            rows = s.recent(limit=1)
            assert rows[0]["action_status"] == "executed"
        finally:
            os.unlink(db_path)

    def test_daily_pnl_pct_returns_zero_when_no_trades(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            s = storage.Storage(db_path)
            assert s.daily_pnl_pct(account_value=10000) == 0.0
        finally:
            os.unlink(db_path)

    def test_daily_pnl_pct_returns_percentage(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            s = storage.Storage(db_path)
            cycle_id = s.new_cycle("/tmp/test.png")
            s.set_action(cycle_id, "executed_auto", mcp_result={"pnl": 300.0})
            pnl_pct = s.daily_pnl_pct(account_value=10000)
            assert pnl_pct == 3.0
        finally:
            os.unlink(db_path)

    def test_daily_pnl_pct_returns_zero_when_account_value_is_zero(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            s = storage.Storage(db_path)
            cycle_id = s.new_cycle("/tmp/test.png")
            s.set_action(cycle_id, "executed_auto", mcp_result={"pnl": 300.0})
            assert s.daily_pnl_pct(account_value=0) == 0.0
        finally:
            os.unlink(db_path)

    def test_recent_returns_ordered_results(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            s = storage.Storage(db_path)
            s.new_cycle("/tmp/test1.png")
            s.new_cycle("/tmp/test2.png")
            rows = s.recent(limit=1)
            assert len(rows) == 1
        finally:
            os.unlink(db_path)


class TestStalePositionFiltering:
    """Tests for filtering stale positions from MCP results."""

    def _make_scheduler(self):
        """Create a Scheduler with mocked dependencies for testing."""
        loop = __import__("asyncio").new_event_loop()
        cfg = {"ctrader_mcp": {"url": "http://localhost:8000", "account_id": "123"}}
        s = Scheduler.__new__(Scheduler)
        s.cfg = cfg
        s._closed_position_ids = set()
        s.mcp = MagicMock()
        s._loop = loop
        return s

    def test_get_position_id_various_keys(self):
        """Position ID extracted from multiple possible key names."""
        s = self._make_scheduler()
        assert s._get_position_id({"id": "123"}) == "123"
        assert s._get_position_id({"position_id": 456}) == "456"
        assert s._get_position_id({"positionId": "789"}) == "789"
        assert s._get_position_id({"foo": "bar"}) is None

    @pytest.mark.asyncio
    async def test_filtered_positions_removes_closed_ids(self):
        """Positions whose IDs are in _closed_position_ids are filtered out."""
        s = self._make_scheduler()
        s._closed_position_ids = {"123"}
        s.mcp.get_open_positions = AsyncMock(return_value=[
            {"id": "123", "symbol": "BTCUSD"},
            {"id": "456", "symbol": "ETHUSD"},
        ])
        result = await s.get_filtered_positions()
        assert len(result) == 1
        assert result[0]["id"] == "456"

    @pytest.mark.asyncio
    async def test_filtered_positions_no_closed_ids(self):
        """When no positions are tracked as closed, all are returned."""
        s = self._make_scheduler()
        positions = [{"id": "123", "symbol": "BTCUSD"}]
        s.mcp.get_open_positions = AsyncMock(return_value=positions)
        result = await s.get_filtered_positions()
        assert result == positions

    def test_clear_closed_position_ids(self):
        """clear_closed_position_ids empties the tracking set."""
        s = self._make_scheduler()
        s._closed_position_ids = {"123", "456"}
        s.clear_closed_position_ids()
        assert s._closed_position_ids == set()

    @pytest.mark.asyncio
    async def test_filtered_positions_handles_mcp_error(self):
        """If MCP raises, empty list is returned."""
        s = self._make_scheduler()
        s.mcp.get_open_positions = AsyncMock(side_effect=ConnectionError("MCP down"))
        result = await s.get_filtered_positions()
        assert result == []