'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getBacktests } from '@/lib/api';
import type { BacktestListItem } from '@/types/api';
import LoadingState from '@/components/ui/LoadingState';
import ErrorState from '@/components/ui/ErrorState';
import EmptyState from '@/components/ui/EmptyState';
import StatusBadge from '@/components/ui/StatusBadge';
import { formatDateTime, formatCurrency, formatPercent, pnlColor } from '@/lib/utils';

export default function BacktestsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backtests, setBacktests] = useState<BacktestListItem[]>([]);

  const load = () => {
    setLoading(true);
    setError(null);
    getBacktests(100, 0)
      .then((res) => setBacktests(res.items))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <LoadingState message="Loading backtests…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Backtest Runs</h1>
        <Link
          href="/backtests/new"
          className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 text-sm font-medium"
        >
          New Backtest
        </Link>
      </div>

      {backtests.length === 0 ? (
        <EmptyState
          title="No backtests found"
          message="Create your first backtest to get started."
          action={
            <Link href="/backtests/new" className="text-blue-600 hover:text-blue-800 text-sm font-medium">
              Create Backtest →
            </Link>
          }
        />
      ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Strategy</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Timeframe</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Return</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Trades</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {backtests.map((bt) => (
                  <tr key={bt.run_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <Link href={`/backtests/${bt.run_id}`} className="text-sm font-medium text-blue-600 hover:text-blue-800">
                        {bt.strategy_id} v{bt.strategy_version}
                      </Link>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900">{bt.symbol}</td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500">{bt.timeframe}</td>
                    <td className="px-4 py-3 whitespace-nowrap"><StatusBadge status={bt.status} /></td>
                    <td className={`px-4 py-3 whitespace-nowrap text-sm text-right font-medium ${pnlColor(bt.total_return_pct)}`}>
                      {formatPercent(bt.total_return_pct)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-right text-gray-500">{bt.total_trades ?? '—'}</td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-400">{formatDateTime(bt.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
