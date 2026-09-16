import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.backtesting.schemas import BacktestEquityPoint, BacktestTradeRecord
from app.backtesting.service import BacktestApplicationService
from app.models.backtesting import BacktestRunModel
from app.schemas.api_backtesting import (
    BacktestCreateRequest,
    BacktestDetailResponse,
    BacktestListPaginated,
    BacktestListResponse,
)


# Since we don't have DI framework setup here fully yet, we will just stub the dependency getter
# This usually comes from the app dependencies
def get_backtest_service() -> BacktestApplicationService:
    """Dependency provider for BacktestApplicationService. Overridden in tests."""
    raise NotImplementedError("Dependency injection not configured for production yet.")


router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])


@router.post("", response_model=BacktestDetailResponse)
async def create_backtest(
    request: BacktestCreateRequest,
    service: BacktestApplicationService = Depends(get_backtest_service),  # noqa: B008
) -> BacktestDetailResponse:
    """Create and execute a backtest synchronously.

    Returns the persisted BacktestRun.  Configuration errors (missing strategy,
    invalid dates) are returned as HTTP 400.  Unexpected server faults are
    HTTP 500 — never exposing internal stack details to the caller.
    """
    try:
        run_model = await service.execute_backtest(request)
    except ValueError as exc:
        # Known application-layer validation errors (missing strategy, etc.)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Catch-all: log server-side, return a safe generic message
        raise HTTPException(status_code=500, detail="Internal server error.") from exc
    return _map_model_to_detail(run_model)


@router.get("", response_model=BacktestListPaginated)
async def list_backtests(
    limit: int = 100,
    offset: int = 0,
    service: Any = Depends(get_backtest_service),  # noqa: B008
) -> BacktestListPaginated:
    """List summary of backtest runs."""
    runs = await service.repository.list_runs(limit=limit, offset=offset)
    # Simple count hack for now
    total = len(runs)

    items = []
    for r in runs:
        items.append(BacktestListResponse.model_validate(r))

    return BacktestListPaginated(items=items, total=total)


@router.get("/{run_id}", response_model=BacktestDetailResponse)
async def get_backtest(
    run_id: uuid.UUID,
    service: Any = Depends(get_backtest_service),  # noqa: B008
) -> BacktestDetailResponse:
    """Get complete details of a backtest run."""
    run_model = await service.repository.get_by_id(run_id)
    if not run_model:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    return _map_model_to_detail(run_model)


def _map_model_to_detail(model: BacktestRunModel) -> BacktestDetailResponse:
    """Map DB model to detailed API response schemas."""
    # We load JSONB back to domain models cleanly
    trades = [BacktestTradeRecord.model_validate(t) for t in model.trades_json]
    equity_curve = [BacktestEquityPoint.model_validate(p) for p in model.equity_curve_json]

    return BacktestDetailResponse(
        run_id=model.run_id,
        status=model.status,
        strategy_id=model.strategy_id,
        strategy_version=model.strategy_version,
        symbol=model.symbol,
        timeframe=model.timeframe,
        start_time=model.start_time,
        end_time=model.end_time,
        created_at=model.created_at,
        completed_at=model.completed_at,
        initial_capital=model.initial_capital,
        commission_pct=model.commission_pct,
        slippage_pct=model.slippage_pct,
        parameters=model.parameters,
        final_equity=model.final_equity,
        total_return_pct=model.total_return_pct,
        realized_pnl=model.realized_pnl,
        unrealized_pnl=model.unrealized_pnl,
        total_trades=model.total_trades,
        winning_trades=model.winning_trades,
        losing_trades=model.losing_trades,
        win_rate=model.win_rate,
        max_drawdown_pct=model.max_drawdown_pct,
        peak_equity=model.peak_equity,
        minimum_equity=model.minimum_equity,
        average_win=model.average_win,
        average_loss=model.average_loss,
        largest_win=model.largest_win,
        largest_loss=model.largest_loss,
        error_message=model.error_message,
        trades=trades,
        equity_curve=equity_curve,
    )
