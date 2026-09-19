'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import StatCard from '@/components/Dashboard/StatCard';
import LoadingState from '@/components/ui/LoadingState';
import ErrorState from '@/components/ui/ErrorState';
import StatusBadge from '@/components/ui/StatusBadge';
import { getSystemStatus, getHealth, getStrategies, getBacktests } from '@/lib/api';
import type { SystemStatus, HealthResponse, StrategyListItem, BacktestListPaginated } from '@/types/api';
import { formatDateTime } from '@/lib/utils';

export default function DashboardPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [strategies, setStrategies] = useState<StrategyListItem[]>([]);
  const [backtests, setBacktests] = useState<BacktestListPaginated | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      getSystemStatus(),
      getHealth(),
      getStrategies(),
      getBacktests(5, 0),
    ]).then(([s, h, strats, bt]) => {
      setStatus(s);
      setHealth(h);
      setStrategies(strats as StrategyListItem[]);
      setBacktests(bt as BacktestListPaginated);
      setLoading(false);
    }).catch((err) => {
      console.error(err);
      setError('Failed to load dashboard data. The backend might be unavailable.');
      setLoading(false);
    });
  };

  useEffect(() => { load(); }, []);

  if (loading) return <LoadingState message="Loading dashboard…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  const completedCount = backtests?.items.filter((b) => b.status === 'COMPLETED').length ?? 0;
  const failedCount = backtests?.items.filter((b) => b.status === 'FAILED').length ?? 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        {status && (
          <div className="text-sm text-gray-500">
            v{status.version} · Uptime: {Math.floor(status.uptime_seconds / 60)}m
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Trading Mode"
          value={status?.trading_mode ?? 'BACKTEST'}
          sublabel="Simulation only"
        />
        <StatCard label="Strategies" value={strategies.length} />
        <StatCard label="Total Backtests" value={backtests?.total ?? 0} />
        <StatCard
          label="System Health"
          value={health ? (health.status.charAt(0).toUpperCase() + health.status.slice(1)) : 'Unknown'}
          sublabel={status?.configuration_valid ? 'Config Valid' : 'Config Invalid'}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Backtests */}
        <div className="bg-white rounded-lg shadow">
          <div className="px-5 py-4 border-b border-gray-200 flex justify-between items-center">
            <h2 className="font-semibold text-gray-900">Recent Backtests</h2>
            <Link href="/backtests" className="text-sm text-blue-600 hover:text-blue-800">
              View all →
            </Link>
          </div>
          {backtests && backtests.items.length > 0 ? (
            <ul className="divide-y divide-gray-100">
              {backtests.items.map((bt) => (
                <li key={bt.run_id} className="px-5 py-3 hover:bg-gray-50">
                  <Link href={`/backtests/${bt.run_id}`} className="flex justify-between items-center">
                    <div>
                      <span className="text-sm font-medium text-gray-900">
                        {bt.strategy_id} v{bt.strategy_version}
                      </span>
                      <span className="text-xs text-gray-500 ml-2">{bt.symbol}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={bt.status} />
                      <span className="text-xs text-gray-400">{formatDateTime(bt.created_at)}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-5 py-8 text-sm text-gray-500 text-center">No backtests yet.</p>
          )}
        </div>

        {/* Strategies */}
        <div className="bg-white rounded-lg shadow">
          <div className="px-5 py-4 border-b border-gray-200 flex justify-between items-center">
            <h2 className="font-semibold text-gray-900">Strategies</h2>
            <Link href="/strategies" className="text-sm text-blue-600 hover:text-blue-800">
              View all →
            </Link>
          </div>
          {strategies.length > 0 ? (
            <ul className="divide-y divide-gray-100">
              {strategies.map((s) => (
                <li key={s.strategy_id} className="px-5 py-3 hover:bg-gray-50">
                  <Link href={`/strategies/${s.strategy_id}`} className="flex justify-between items-center">
                    <div>
                      <span className="text-sm font-medium text-gray-900">{s.name}</span>
                      <span className="text-xs text-gray-500 ml-2">{s.strategy_id}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={s.status} />
                      <span className="text-xs text-gray-400">{s.version_count} versions</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-5 py-8 text-sm text-gray-500 text-center">No strategies registered.</p>
          )}
        </div>
      </div>
    </div>
  );
}
