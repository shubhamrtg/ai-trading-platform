import logging
import re
from datetime import UTC, datetime
from decimal import Decimal

from app.backtesting.engine import BacktestEngine
from app.backtesting.provider import MarketDataProvider
from app.backtesting.repository import BacktestRunRepository
from app.backtesting.schemas import BacktestRequest, BacktestResult, BacktestRun
from app.models.backtesting import BacktestRunModel
from app.models.enums import BacktestStatus
from app.schemas.api_backtesting import BacktestCreateRequest
from app.strategies.repository import StrategyVersionRepository

logger = logging.getLogger(__name__)


class BacktestApplicationService:
    """Orchestrates backtest lifecycle: API request → persistence → Phase D engine → result."""

    def __init__(
        self,
        repository: BacktestRunRepository,
        strategy_repo: StrategyVersionRepository,
        engine: BacktestEngine,
        provider: MarketDataProvider,
    ):
        self.repository = repository
        self.strategy_repo = strategy_repo
        self.engine = engine
        self.provider = provider

    async def execute_backtest(self, request: BacktestCreateRequest) -> BacktestRunModel:
        """Run a complete backtest lifecycle."""

        # 1. Idempotency Check
        if request.idempotency_key:
            existing_run = await self.repository.get_by_idempotency_key(request.idempotency_key)
            if existing_run:
                return existing_run

        # 2. Strategy resolution and validation
        # Verify the strategy version exists via Phase C repo
        strat_version = await self.strategy_repo.get_executable_version(
            request.strategy_id, request.strategy_version
        )
        if not strat_version:
            raise ValueError(
                f"Strategy version {request.strategy_id} v{request.strategy_version} not found."
            )

        # 3. Create run record in CREATED state
        run_model = BacktestRunModel(
            status=BacktestStatus.CREATED,
            idempotency_key=request.idempotency_key,
            strategy_id=request.strategy_id,
            strategy_version=request.strategy_version,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_time=request.start_time,
            end_time=request.end_time,
            initial_capital=request.initial_capital,
            commission_pct=request.commission_pct,
            slippage_pct=request.slippage_pct,
            parameters=request.parameters,
        )
        run_model, created = await self.repository.create(run_model)

        # If create() resolved an idempotency collision, the returned model is
        # the *existing* persisted run (not our freshly built object) and created is False.
        # Return it directly — do not re-execute.
        if not created:
            return run_model

        # 4. Update to RUNNING
        run_model.status = BacktestStatus.RUNNING
        run_model = await self.repository.update(run_model)

        try:
            # Phase C enforces strict Decimal types. JSON has no Decimal type, so we coerce
            # numeric strings in parameters to Decimal at the Application Service boundary.
            coerced_params: dict[str, object] = {}
            for k, v in request.parameters.items():
                if isinstance(v, str) and re.match(r"^-?\d+(\.\d+)?$", v):
                    coerced_params[k] = Decimal(v)
                else:
                    coerced_params[k] = v

            # Prepare Phase D engine request
            engine_request = BacktestRequest(
                strategy_id=request.strategy_id,
                strategy_version=request.strategy_version,
                symbol=request.symbol,
                timeframe=request.timeframe,
                start_time=request.start_time,
                end_time=request.end_time,
                initial_capital=request.initial_capital,
                commission_pct=request.commission_pct,
                slippage_pct=request.slippage_pct,
                parameters=coerced_params,
            )

            # Obtain historical candle stream
            candle_provider = self.provider.get_candles(
                symbol=request.symbol,
                timeframe=request.timeframe,
                start_time=request.start_time,
                end_time=request.end_time,
            )

            # 5. Execute via Phase D BacktestEngine
            run_result: BacktestRun = await self.engine.run_backtest(
                engine_request, candle_provider
            )

            # 6. Save results back
            if run_result.status == BacktestStatus.COMPLETED and run_result.result:
                res: BacktestResult = run_result.result
                m = res.metrics

                run_model.final_equity = m.final_equity
                run_model.total_return_pct = m.total_return_pct
                run_model.realized_pnl = m.realized_pnl
                run_model.unrealized_pnl = m.unrealized_pnl
                run_model.total_trades = m.total_trades
                run_model.winning_trades = m.winning_trades
                run_model.losing_trades = m.losing_trades
                run_model.win_rate = m.win_rate
                run_model.max_drawdown_pct = m.max_drawdown_pct
                run_model.peak_equity = m.peak_equity
                run_model.minimum_equity = m.minimum_equity
                run_model.average_win = m.average_win
                run_model.average_loss = m.average_loss
                run_model.largest_win = m.largest_win
                run_model.largest_loss = m.largest_loss

                # Serialize using model_dump(mode='json') to handle Decimal/datetime cleanly.
                run_model.trades_json = [t.model_dump(mode="json") for t in res.trades]
                run_model.equity_curve_json = [p.model_dump(mode="json") for p in res.equity_curve]

                run_model.status = BacktestStatus.COMPLETED
            else:
                run_model.status = BacktestStatus.FAILED
                run_model.error_message = run_result.error_message

        except Exception as e:
            logger.exception("Error executing backtest")
            run_model.status = BacktestStatus.FAILED
            run_model.error_message = str(e)

        run_model.completed_at = datetime.now(UTC)
        run_model = await self.repository.update(run_model)

        return run_model
