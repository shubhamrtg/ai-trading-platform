"""Deterministic Backtesting Engine.

Orchestrates strategy execution against historical data, ensuring
chronological integrity, isolation, and safe simulated execution.
"""

from collections.abc import AsyncGenerator
from decimal import Decimal

from app.backtesting.schemas import BacktestMetrics, BacktestRequest, BacktestResult, BacktestRun
from app.backtesting.simulator import BacktestExecutionSimulator
from app.models.enums import BacktestStatus
from app.schemas.market_data import Candle
from app.strategies.service import StrategyExecutionService


class BacktestValidationError(Exception):
    """Raised when historical data is invalid or out-of-order."""


class BacktestEngine:
    """Core engine for deterministic backtesting."""

    def __init__(self, execution_service: StrategyExecutionService):
        self.execution_service = execution_service

    async def run_backtest(
        self,
        request: BacktestRequest,
        candle_provider: AsyncGenerator[Candle, None],
    ) -> BacktestRun:
        """Run a completely isolated, deterministic backtest."""
        try:
            if request.start_time >= request.end_time:
                raise BacktestValidationError("start_time must be strictly before end_time.")

            # 1. Initialize authoritative Strategy Runner
            runner = await self.execution_service.create_runner(
                strategy_id=request.strategy_id,
                version=request.strategy_version,
                parameters_dict=request.parameters,
            )

            # 2. Initialize execution simulator
            simulator = BacktestExecutionSimulator(
                initial_capital=request.initial_capital,
                commission_pct=request.commission_pct,
                slippage_pct=request.slippage_pct,
            )

            # 3. Process chronological data
            last_timestamp = None
            last_candle = None

            async for candle in candle_provider:
                if candle.timestamp < request.start_time or candle.timestamp > request.end_time:
                    raise BacktestValidationError("Candle timestamp is outside requested window.")

                if last_timestamp and candle.timestamp <= last_timestamp:
                    raise BacktestValidationError(
                        "Candles must be strictly chronological and non-duplicate."
                    )
                if candle.symbol != request.symbol or candle.timeframe != request.timeframe:
                    raise BacktestValidationError(
                        "Inconsistent symbol or timeframe in candle data."
                    )

                last_timestamp = candle.timestamp
                last_candle = candle

                # Simulate execution (fills from previous candle signals + accounting)
                simulator.process_candle(candle)

                # Evaluate strategy on current candle
                signal = runner.process_candle(candle)

                if signal:
                    simulator.queue_signal(signal)

            if not last_candle:
                raise BacktestValidationError("No historical data provided.")

            # 4. Handle end of backtest open positions
            simulator.force_close_position(last_candle)

            # 5. Calculate Metrics
            metrics = self._calculate_metrics(simulator, request.initial_capital)

            business_result = BacktestResult(
                request=request,
                metrics=metrics,
                trades=simulator.trades,
                equity_curve=simulator.equity_curve,
            )

            return BacktestRun(
                request=request, status=BacktestStatus.COMPLETED, result=business_result
            )

        except Exception as e:
            return BacktestRun(
                request=request,
                status=BacktestStatus.FAILED,
                error_message=str(e),
            )

    def _calculate_metrics(
        self, simulator: BacktestExecutionSimulator, initial_capital: Decimal
    ) -> BacktestMetrics:
        """Calculate deterministic performance metrics."""
        trades = simulator.trades
        total_trades = len(trades)

        winning_trades = [t for t in trades if t.net_pnl > 0]
        losing_trades = [t for t in trades if t.net_pnl <= 0]

        realized_pnl = sum((t.net_pnl for t in trades), Decimal("0.0"))

        final_equity = simulator.cash
        total_return_pct = (
            (final_equity - initial_capital) / initial_capital
            if initial_capital > 0
            else Decimal("0.0")
        )

        win_rate = (
            Decimal(len(winning_trades)) / Decimal(total_trades)
            if total_trades > 0
            else Decimal("0.0")
        )

        max_drawdown_pct = max(
            (p.drawdown_pct for p in simulator.equity_curve), default=Decimal("0.0")
        )

        avg_win = (
            sum((t.net_pnl for t in winning_trades), Decimal("0.0")) / len(winning_trades)
            if winning_trades
            else None
        )
        avg_loss = (
            sum((t.net_pnl for t in losing_trades), Decimal("0.0")) / len(losing_trades)
            if losing_trades
            else None
        )

        largest_win = (
            max((t.net_pnl for t in winning_trades), default=None) if winning_trades else None
        )
        largest_loss = (
            min((t.net_pnl for t in losing_trades), default=None) if losing_trades else None
        )

        return BacktestMetrics(
            initial_capital=initial_capital,
            final_equity=final_equity,
            total_return_pct=total_return_pct,
            realized_pnl=realized_pnl,
            unrealized_pnl=Decimal("0.0"),  # End of backtest forces close, so 0 unrealized
            total_trades=total_trades,
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=win_rate,
            max_drawdown_pct=max_drawdown_pct,
            peak_equity=simulator.peak_equity,
            minimum_equity=min((p.equity for p in simulator.equity_curve), default=initial_capital),
            average_win=avg_win,
            average_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
        )
