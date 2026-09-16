"""Execution Simulator for Backtesting.

Handles simulated order fills, accounting, and position tracking.
Enforces NEXT-OPEN execution to prevent look-ahead bias.
"""

from datetime import datetime
from decimal import Decimal

from app.backtesting.schemas import BacktestEquityPoint, BacktestTradeRecord
from app.models.enums import OrderSide
from app.schemas.market_data import Candle
from app.schemas.signal import Signal


class BacktestPosition:
    def __init__(
        self,
        strategy_id: str,
        strategy_version: str,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        entry_price: Decimal,
        entry_timestamp: datetime,
        entry_fee: Decimal,
        entry_slippage: Decimal,
    ):
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version
        self.symbol = symbol
        self.side = side
        self.quantity = quantity
        self.entry_price = entry_price
        self.entry_timestamp = entry_timestamp
        self.entry_fee = entry_fee
        self.entry_slippage = entry_slippage


class BacktestExecutionSimulator:
    """Simulates market execution strictly avoiding look-ahead."""

    def __init__(self, initial_capital: Decimal, commission_pct: Decimal, slippage_pct: Decimal):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct

        self.position: BacktestPosition | None = None
        self.pending_signals: list[Signal] = []

        self.trades: list[BacktestTradeRecord] = []
        self.equity_curve: list[BacktestEquityPoint] = []
        self.peak_equity = initial_capital
        self._trade_count = 0

    def process_candle(self, candle: Candle) -> None:
        """Process execution for a candle and mark-to-market.

        Must be called sequentially for each chronological candle.
        """
        # 1. Execute pending signals from the PREVIOUS candle at current OPEN price
        for signal in self.pending_signals:
            self._execute_signal(signal, candle)
        self.pending_signals.clear()

        # 2. Mark-to-market accounting
        position_value = Decimal("0.0")
        if self.position:
            # We only implement LONG positions for simple baseline
            position_value = self.position.quantity * candle.close

        equity = self.cash + position_value
        if equity > self.peak_equity:
            self.peak_equity = equity

        drawdown_pct = Decimal("0.0")
        if self.peak_equity > 0:
            drawdown_pct = (self.peak_equity - equity) / self.peak_equity

        self.equity_curve.append(
            BacktestEquityPoint(
                timestamp=candle.timestamp,
                cash=self.cash,
                position_value=position_value,
                equity=equity,
                drawdown_pct=drawdown_pct,
            )
        )

    def queue_signal(self, signal: Signal) -> None:
        """Queue a signal to be executed at the NEXT candle's open."""
        self.pending_signals.append(signal)

    def force_close_position(self, candle: Candle) -> None:
        """Force close an open position at the end of the backtest using candle close."""
        if self.position:
            # Execute exit at the candle's close price instead of next open
            self._execute_exit(self.position, candle.close, candle.timestamp)
            self.position = None

            # Record the final equity state
            equity = self.cash
            if equity > self.peak_equity:
                self.peak_equity = equity

            drawdown_pct = Decimal("0.0")
            if self.peak_equity > 0:
                drawdown_pct = (self.peak_equity - equity) / self.peak_equity

            # To ensure the final point accurately reflects the post-close equity,
            # we overwrite the last mark-to-market point if it's on the same timestamp,
            # or append if needed.
            point = BacktestEquityPoint(
                timestamp=candle.timestamp,
                cash=self.cash,
                position_value=Decimal("0.0"),
                equity=equity,
                drawdown_pct=drawdown_pct,
            )

            if self.equity_curve and self.equity_curve[-1].timestamp == candle.timestamp:
                self.equity_curve[-1] = point
            else:
                self.equity_curve.append(point)

        self.pending_signals.clear()

    def _execute_signal(self, signal: Signal, candle: Candle) -> None:
        """Simulate a market execution at the open price."""
        if signal.side == OrderSide.BUY:
            if self.position is not None:
                # Already long, ignore duplicate BUY for baseline simple semantics
                return

            # Execute LONG ENTRY
            # Slippage makes the purchase more expensive
            slippage_amount = candle.open * (self.slippage_pct / Decimal("100.0"))
            fill_price = candle.open + slippage_amount

            # Use all available cash for simplicity in this baseline
            # Must ensure cash cannot go negative due to commissions
            commission_rate = self.commission_pct / Decimal("100.0")
            quantity = self.cash / (fill_price * (Decimal("1.0") + commission_rate))

            notional = quantity * fill_price
            fee = notional * commission_rate

            self.cash -= notional + fee

            self.position = BacktestPosition(
                strategy_id=signal.strategy_id,
                strategy_version=signal.strategy_version,
                symbol=signal.symbol,
                side=OrderSide.BUY,
                quantity=quantity,
                entry_price=fill_price,
                entry_timestamp=candle.timestamp,
                entry_fee=fee,
                entry_slippage=slippage_amount * quantity,
            )

        elif signal.side == OrderSide.SELL:
            if self.position is None:
                # We do not support short selling in this baseline
                return

            if self.position.side == OrderSide.BUY:
                # Execute LONG EXIT
                # Slippage makes the sale less profitable
                slippage_amount = candle.open * (self.slippage_pct / Decimal("100.0"))
                fill_price = candle.open - slippage_amount
                self._execute_exit(self.position, fill_price, candle.timestamp, slippage_amount)
                self.position = None

    def _execute_exit(
        self,
        position: BacktestPosition,
        fill_price: Decimal,
        timestamp: datetime,
        slippage_per_unit: Decimal = Decimal("0.0"),
    ) -> None:
        notional = position.quantity * fill_price
        fee = notional * (self.commission_pct / Decimal("100.0"))

        self.cash += notional - fee

        exit_slippage = slippage_per_unit * position.quantity
        total_slippage = position.entry_slippage + exit_slippage
        total_fees = position.entry_fee + fee

        gross_pnl = (fill_price - position.entry_price) * position.quantity
        net_pnl = gross_pnl - total_fees

        entry_notional = position.quantity * position.entry_price
        return_pct = net_pnl / entry_notional if entry_notional > 0 else Decimal("0.0")

        self._trade_count += 1

        self.trades.append(
            BacktestTradeRecord(
                trade_sequence=self._trade_count,
                strategy_id=position.strategy_id,
                strategy_version=position.strategy_version,
                symbol=position.symbol,
                side=position.side,
                quantity=position.quantity,
                entry_timestamp=position.entry_timestamp,
                entry_price=position.entry_price,
                exit_timestamp=timestamp,
                exit_price=fill_price,
                gross_pnl=gross_pnl,
                fees=total_fees,
                slippage=total_slippage,
                net_pnl=net_pnl,
                return_percentage=return_pct,
            )
        )
