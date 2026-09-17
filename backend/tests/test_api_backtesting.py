import datetime
from decimal import Decimal
from typing import Any

import pytest
from app.api.backtesting import get_backtest_service
from app.backtesting.engine import BacktestEngine
from app.backtesting.provider import DummyMarketDataProvider, MarketDataProvider
from app.backtesting.repository import BacktestRunRepository
from app.backtesting.service import BacktestApplicationService
from app.main import create_app
from app.models.backtesting import BacktestRunModel
from app.models.enums import BacktestStatus
from app.schemas.api_backtesting import BacktestCreateRequest
from app.schemas.market_data import Candle
from app.strategies.repository import StrategyVersionRepository
from app.strategies.service import StrategyExecutionService
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def backtest_service(db_session: AsyncSession) -> BacktestApplicationService:
    repo = BacktestRunRepository(db_session)
    strat_repo = StrategyVersionRepository(db_session)
    strat_service = StrategyExecutionService(strat_repo)
    engine = BacktestEngine(strat_service)
    provider = DummyMarketDataProvider()
    return BacktestApplicationService(repo, strat_repo, engine, provider)


@pytest.mark.asyncio
async def test_backtest_lifecycle(
    db_session: AsyncSession,
    backtest_service: BacktestApplicationService,
) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    # Make sure we have the strategy version
    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")
    await db_session.commit()

    app = create_app()
    app.dependency_overrides[get_backtest_service] = lambda: backtest_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        req = BacktestCreateRequest(
            strategy_id="MA_Crossover_Reference",
            strategy_version="1.0.0",
            symbol="BTC-USD",
            timeframe="1d",
            start_time=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2023, 1, 10, tzinfo=datetime.UTC),
            initial_capital=Decimal("100000.0"),
            commission_pct=Decimal("0.0"),
            slippage_pct=Decimal("0.0"),
            # The service coerces numeric strings to Decimal at the application boundary
            parameters={"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"},
            idempotency_key="test-key-1",
        )

        # ---- CREATE ----
        resp = await client.post("/api/v1/backtests", json=req.model_dump(mode="json"))
        assert resp.status_code == 200, resp.text
        data: dict[str, Any] = resp.json()
        run_id = data["run_id"]

        assert data["status"] == BacktestStatus.COMPLETED.value
        assert data["strategy_id"] == "MA_Crossover_Reference"
        assert data["total_trades"] is not None
        assert len(data["trades"]) > 0

        # ---- IDEMPOTENCY ----
        resp2 = await client.post("/api/v1/backtests", json=req.model_dump(mode="json"))
        assert resp2.status_code == 200
        data2: dict[str, Any] = resp2.json()
        assert data2["run_id"] == run_id  # Same key returns same run

        # ---- GET LIST ----
        resp3 = await client.get("/api/v1/backtests")
        assert resp3.status_code == 200
        list_data: dict[str, Any] = resp3.json()
        assert list_data["total"] >= 1
        assert any(item["run_id"] == run_id for item in list_data["items"])

        # ---- GET DETAIL ----
        resp4 = await client.get(f"/api/v1/backtests/{run_id}")
        assert resp4.status_code == 200
        detail_data: dict[str, Any] = resp4.json()
        assert detail_data["run_id"] == run_id
        # Decimal serialisation may produce trailing zeros; compare with Decimal
        assert Decimal(detail_data["initial_capital"]) == Decimal("100000.0")

        # ---- GET 404 ----
        resp_404 = await client.get("/api/v1/backtests/00000000-0000-0000-0000-000000000000")
        assert resp_404.status_code == 404

        # ---- FAILURE: unknown strategy → 400 ----
        # Use no idempotency key (fresh request) to avoid hitting idempotency cache
        req_fail = BacktestCreateRequest(
            strategy_id="non_existent",
            strategy_version="9.9.9",
            symbol="BTC-USD",
            timeframe="1d",
            start_time=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2023, 1, 10, tzinfo=datetime.UTC),
            parameters={"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"},
            idempotency_key=None,
        )
        resp_fail = await client.post("/api/v1/backtests", json=req_fail.model_dump(mode="json"))
        assert resp_fail.status_code == 400

        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 1 — Idempotency UNIQUE collision (regression for concurrent race)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idempotency_collision_handled(
    db_session: AsyncSession,
    backtest_service: BacktestApplicationService,
) -> None:
    """Simulate the concurrent-race scenario.

    We pre-insert a BacktestRunModel with a known idempotency_key directly
    into the DB (simulating a concurrent winner), then call the service with
    the same key.  The service's optimistic check sees "not found" (we bypass
    the in-memory check), but the INSERT hits the UNIQUE constraint.

    The repository must catch IntegrityError, rollback, re-query, and return
    the existing run.  No HTTP 500 may be produced.
    """
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")
    await db_session.commit()

    # --- Pre-insert the "winner" run directly at the DB level ---
    winner = BacktestRunModel(
        status=BacktestStatus.COMPLETED,
        idempotency_key="race-collision-key",
        strategy_id="MA_Crossover_Reference",
        strategy_version="1.0.0",
        symbol="BTC-USD",
        timeframe="1d",
        start_time=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
        end_time=datetime.datetime(2023, 1, 10, tzinfo=datetime.UTC),
        initial_capital=Decimal("100000.0"),
        commission_pct=Decimal("0.0"),
        slippage_pct=Decimal("0.0"),
        parameters={},
    )
    db_session.add(winner)
    await db_session.commit()
    await db_session.refresh(winner)
    winner_run_id = winner.run_id

    # --- Now call the service with the same key.
    # Patch get_by_idempotency_key to return None on the FIRST call (simulating
    # the race: the optimistic check doesn't see it yet), but behave normally
    # on subsequent calls (the re-query after IntegrityError).
    original_get = backtest_service.repository.get_by_idempotency_key
    call_count = 0

    async def patched_get(key: str) -> BacktestRunModel | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulate the race: optimistic check returns None
            return None
        # Re-query after IntegrityError — return the real winner
        return await original_get(key)

    backtest_service.repository.get_by_idempotency_key = patched_get  # type: ignore[method-assign]

    req = BacktestCreateRequest(
        strategy_id="MA_Crossover_Reference",
        strategy_version="1.0.0",
        symbol="BTC-USD",
        timeframe="1d",
        start_time=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
        end_time=datetime.datetime(2023, 1, 10, tzinfo=datetime.UTC),
        initial_capital=Decimal("100000.0"),
        commission_pct=Decimal("0.0"),
        slippage_pct=Decimal("0.0"),
        parameters={"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"},
        idempotency_key="race-collision-key",
    )

    # This must NOT raise — the repository catches IntegrityError
    result = await backtest_service.execute_backtest(req)

    # Must return the winner, not a new run
    assert result.run_id == winner_run_id
    assert result.status == BacktestStatus.COMPLETED

    # Verify exactly one run exists for this key
    from sqlalchemy import func, select

    count_stmt = select(func.count()).where(
        BacktestRunModel.idempotency_key == "race-collision-key"
    )
    count_result = await db_session.execute(count_stmt)
    assert count_result.scalar() == 1

    # Also verify via the API — no HTTP 500
    app = create_app()
    app.dependency_overrides[get_backtest_service] = lambda: backtest_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.post("/api/v1/backtests", json=req.model_dump(mode="json"))
        # The sequential idempotency check now finds it — returns 200
        assert resp.status_code == 200
        assert resp.json()["run_id"] == str(winner_run_id)

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 2 — FAILED lifecycle persistence (execution failure, not validation)
# ---------------------------------------------------------------------------
class _FailingMarketDataProvider(MarketDataProvider):
    """Provider that yields one valid candle then raises an exception."""

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
    ) -> Any:
        # Yield one valid candle so the engine starts processing
        yield Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=start_time,
            open=Decimal("100.0"),
            high=Decimal("110.0"),
            low=Decimal("90.0"),
            close=Decimal("100.0"),
            volume=Decimal("1000.0"),
            vwap=None,
            trades=None,
        )
        # Then raise — simulating a data-provider or engine failure
        raise RuntimeError("Simulated data provider failure")


@pytest.mark.asyncio
async def test_failed_lifecycle_persistence(
    db_session: AsyncSession,
) -> None:
    """A backtest that fails during execution must persist as FAILED.

    Verifies:
    - Run is persisted with status=FAILED
    - error_message is populated (no raw traceback)
    - No result metrics are fabricated
    - GET detail returns the FAILED run
    """
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")
    await db_session.commit()

    repo = BacktestRunRepository(db_session)
    strat_repo = StrategyVersionRepository(db_session)
    strat_service = StrategyExecutionService(strat_repo)
    engine = BacktestEngine(strat_service)
    failing_provider = _FailingMarketDataProvider()

    service = BacktestApplicationService(repo, strat_repo, engine, failing_provider)

    app = create_app()
    app.dependency_overrides[get_backtest_service] = lambda: service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        req = BacktestCreateRequest(
            strategy_id="MA_Crossover_Reference",
            strategy_version="1.0.0",
            symbol="BTC-USD",
            timeframe="1d",
            start_time=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2023, 1, 10, tzinfo=datetime.UTC),
            initial_capital=Decimal("100000.0"),
            commission_pct=Decimal("0.0"),
            slippage_pct=Decimal("0.0"),
            parameters={"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"},
            idempotency_key=None,
        )

        # The engine itself catches exceptions and returns FAILED —
        # OR the service's own except block catches RuntimeError.
        # Either way the API must return 200 with a FAILED run, not 500.
        resp = await client.post("/api/v1/backtests", json=req.model_dump(mode="json"))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data: dict[str, Any] = resp.json()
        run_id = data["run_id"]

        # Status must be FAILED
        assert data["status"] == BacktestStatus.FAILED.value

        # Error message must be populated but must NOT contain raw traceback
        assert data["error_message"] is not None
        assert len(data["error_message"]) > 0
        assert "Traceback" not in data["error_message"]

        # No fabricated result metrics
        assert data["final_equity"] is None
        assert data["realized_pnl"] is None
        assert data["total_trades"] is None
        assert data["winning_trades"] is None
        assert data["losing_trades"] is None
        assert len(data["trades"]) == 0
        assert len(data["equity_curve"]) == 0

        # completed_at must be set even for failures
        assert data["completed_at"] is not None

        # GET detail must return the same FAILED run
        resp_detail = await client.get(f"/api/v1/backtests/{run_id}")
        assert resp_detail.status_code == 200
        detail: dict[str, Any] = resp_detail.json()
        assert detail["status"] == BacktestStatus.FAILED.value
        assert detail["error_message"] == data["error_message"]
        assert detail["run_id"] == run_id

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 3 — Result and configuration persistence (deterministic values)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_result_configuration_persistence(
    db_session: AsyncSession,
    backtest_service: BacktestApplicationService,
) -> None:
    """Verify a successful run persists and returns correct configuration
    and deterministic result values.

    Uses the DummyMarketDataProvider's known candle pattern to assert
    specific metric values from Phase D.
    """
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")
    await db_session.commit()

    app = create_app()
    app.dependency_overrides[get_backtest_service] = lambda: backtest_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        req = BacktestCreateRequest(
            strategy_id="MA_Crossover_Reference",
            strategy_version="1.0.0",
            symbol="BTC-USD",
            timeframe="1d",
            start_time=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2023, 1, 10, tzinfo=datetime.UTC),
            initial_capital=Decimal("100000.0"),
            commission_pct=Decimal("0.0"),
            slippage_pct=Decimal("0.0"),
            parameters={"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"},
            idempotency_key="config-persist-test",
        )

        resp = await client.post("/api/v1/backtests", json=req.model_dump(mode="json"))
        assert resp.status_code == 200, resp.text
        data: dict[str, Any] = resp.json()

        # ---- Configuration persistence ----
        assert data["strategy_id"] == "MA_Crossover_Reference"
        assert data["strategy_version"] == "1.0.0"
        assert data["symbol"] == "BTC-USD"
        assert data["timeframe"] == "1d"
        assert Decimal(data["initial_capital"]) == Decimal("100000.0")
        assert Decimal(data["commission_pct"]) == Decimal("0.0")
        assert Decimal(data["slippage_pct"]) == Decimal("0.0")

        # start/end must round-trip
        assert "2023-01-01" in data["start_time"]
        assert "2023-01-10" in data["end_time"]

        # ---- Result metrics persistence ----
        assert data["status"] == BacktestStatus.COMPLETED.value
        assert data["final_equity"] is not None
        assert data["total_trades"] is not None
        assert data["total_trades"] > 0
        assert data["realized_pnl"] is not None
        assert data["winning_trades"] is not None
        assert data["losing_trades"] is not None

        # With zero commission/slippage: final_equity = initial + realized_pnl
        final_eq = Decimal(data["final_equity"])
        realized = Decimal(data["realized_pnl"])
        assert final_eq == Decimal("100000.0") + realized

        # Unrealized must be 0 (forced close at end of backtest)
        assert Decimal(data["unrealized_pnl"]) == Decimal("0.0")

        # Trades and equity curve must be non-empty and structurally valid
        assert len(data["trades"]) == data["total_trades"]
        assert len(data["equity_curve"]) > 0

        # Each trade record must have required accounting fields
        for trade in data["trades"]:
            assert "entry_price" in trade
            assert "exit_price" in trade
            assert "gross_pnl" in trade
            assert "fees" in trade
            assert "net_pnl" in trade

        # Each equity point must have required fields
        for point in data["equity_curve"]:
            assert "timestamp" in point
            assert "equity" in point
            assert "drawdown_pct" in point

        # ---- Verify via separate GET detail ----
        run_id = data["run_id"]
        resp_detail = await client.get(f"/api/v1/backtests/{run_id}")
        assert resp_detail.status_code == 200
        detail: dict[str, Any] = resp_detail.json()

        # Detail must match the creation response
        assert detail["run_id"] == run_id
        assert detail["strategy_id"] == data["strategy_id"]
        assert Decimal(detail["final_equity"]) == final_eq
        assert detail["total_trades"] == data["total_trades"]

    app.dependency_overrides.clear()
