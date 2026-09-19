import type { BacktestTradeRecord } from '@/types/api';
import { formatCurrency, formatDateTime, formatPercent, pnlColor } from '@/lib/utils';
import EmptyState from '@/components/ui/EmptyState';

export default function TradesTable({ trades }: { trades: BacktestTradeRecord[] }) {
  if (!trades || trades.length === 0) {
    return <EmptyState title="No trades" message="No simulated trades were generated in this backtest." />;
  }

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-200">
        <h3 className="text-lg font-semibold">Simulated Backtest Trades</h3>
        <p className="text-xs text-amber-600 font-medium mt-1">
          ⚠ These are simulated trades from backtesting — not real broker orders
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">#</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Side</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Qty</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Entry Time</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Entry Price</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Exit Time</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Exit Price</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Net P&L</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Return</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {trades.map((trade) => (
              <tr key={trade.trade_sequence} className="hover:bg-gray-50">
                <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-500">{trade.trade_sequence}</td>
                <td className="px-4 py-2 whitespace-nowrap text-sm font-medium text-gray-900">{trade.symbol}</td>
                <td className="px-4 py-2 whitespace-nowrap text-sm">
                  <span className={trade.side === 'BUY' ? 'text-green-600' : 'text-red-600'}>{trade.side}</span>
                </td>
                <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-700">{trade.quantity}</td>
                <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-500">{formatDateTime(trade.entry_timestamp)}</td>
                <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-700 text-right">{formatCurrency(trade.entry_price)}</td>
                <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-500">{formatDateTime(trade.exit_timestamp)}</td>
                <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-700 text-right">{formatCurrency(trade.exit_price)}</td>
                <td className={`px-4 py-2 whitespace-nowrap text-sm text-right font-medium ${pnlColor(trade.net_pnl)}`}>{formatCurrency(trade.net_pnl)}</td>
                <td className={`px-4 py-2 whitespace-nowrap text-sm text-right ${pnlColor(trade.return_percentage)}`}>{formatPercent(trade.return_percentage)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
