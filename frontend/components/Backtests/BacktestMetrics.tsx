import type { BacktestDetail } from '@/types/api';
import { formatCurrency, formatPercent, pnlColor } from '@/lib/utils';

export default function BacktestMetrics({ backtest }: { backtest: BacktestDetail }) {
  const metrics = [
    { label: 'Initial Capital', value: formatCurrency(backtest.initial_capital) },
    { label: 'Final Equity', value: formatCurrency(backtest.final_equity), color: pnlColor(backtest.final_equity && backtest.initial_capital ? (parseFloat(backtest.final_equity) - parseFloat(backtest.initial_capital)).toString() : null) },
    { label: 'Total Return', value: formatPercent(backtest.total_return_pct), color: pnlColor(backtest.total_return_pct) },
    { label: 'Realized P&L', value: formatCurrency(backtest.realized_pnl), color: pnlColor(backtest.realized_pnl) },
    { label: 'Total Trades', value: backtest.total_trades?.toString() ?? '—' },
    { label: 'Winning Trades', value: backtest.winning_trades?.toString() ?? '—' },
    { label: 'Losing Trades', value: backtest.losing_trades?.toString() ?? '—' },
    { label: 'Win Rate', value: formatPercent(backtest.win_rate) },
    { label: 'Max Drawdown', value: formatPercent(backtest.max_drawdown_pct), color: 'text-red-600' },
    { label: 'Peak Equity', value: formatCurrency(backtest.peak_equity) },
    { label: 'Average Win', value: formatCurrency(backtest.average_win), color: 'text-green-600' },
    { label: 'Average Loss', value: formatCurrency(backtest.average_loss), color: 'text-red-600' },
    { label: 'Largest Win', value: formatCurrency(backtest.largest_win), color: 'text-green-600' },
    { label: 'Largest Loss', value: formatCurrency(backtest.largest_loss), color: 'text-red-600' },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
      {metrics.map((m) => (
        <div key={m.label} className="bg-white rounded-lg shadow px-4 py-3">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{m.label}</p>
          <p className={`mt-1 text-lg font-semibold ${m.color || 'text-gray-900'}`}>{m.value}</p>
        </div>
      ))}
    </div>
  );
}
