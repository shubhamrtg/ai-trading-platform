'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { getBacktest } from '@/lib/api';
import type { BacktestDetail } from '@/types/api';
import LoadingState from '@/components/ui/LoadingState';
import ErrorState from '@/components/ui/ErrorState';
import StatusBadge from '@/components/ui/StatusBadge';
import BacktestMetrics from '@/components/Backtests/BacktestMetrics';
import EquityCurve from '@/components/Backtests/EquityCurve';
import TradesTable from '@/components/Backtests/TradesTable';
import DecisionFlow from '@/components/Backtests/DecisionFlow';
import { formatDateTime, formatCurrency } from '@/lib/utils';

type Tab = 'results' | 'equity' | 'trades' | 'flow';

export default function BacktestDetailPage() {
  const params = useParams();
  const runId = params.runId as string;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backtest, setBacktest] = useState<BacktestDetail | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('results');

  const load = () => {
    setLoading(true);
    setError(null);
    getBacktest(runId)
      .then(setBacktest)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [runId]);

  if (loading) return <LoadingState message="Loading backtest…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!backtest) return <ErrorState title="Backtest not found" />;

  const tabs: { key: Tab; label: string }[] = [
    { key: 'results', label: 'Results' },
    { key: 'equity', label: 'Equity Curve' },
    { key: 'trades', label: `Trades (${backtest.trades.length})` },
    { key: 'flow', label: 'Decision Flow' },
  ];

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-gray-900">
            {backtest.strategy_id} v{backtest.strategy_version}
          </h1>
          <StatusBadge status={backtest.status} />
        </div>
        <p className="text-sm text-gray-500 mt-1">
          {backtest.symbol} · {backtest.timeframe} · {formatDateTime(backtest.created_at)}
        </p>
      </div>

      {/* Configuration */}
      <div className="bg-white rounded-lg shadow p-5 mb-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Configuration</h2>
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div>
            <dt className="text-gray-500">Date Range</dt>
            <dd className="text-gray-900">{formatDateTime(backtest.start_time)} — {formatDateTime(backtest.end_time)}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Initial Capital</dt>
            <dd className="text-gray-900">{formatCurrency(backtest.initial_capital)}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Commission</dt>
            <dd className="text-gray-900">{backtest.commission_pct}%</dd>
          </div>
          <div>
            <dt className="text-gray-500">Slippage</dt>
            <dd className="text-gray-900">{backtest.slippage_pct}%</dd>
          </div>
        </dl>
      </div>

      {/* Error message for failed backtests */}
      {backtest.status === 'FAILED' && backtest.error_message && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
          <h3 className="text-sm font-semibold text-red-800">Backtest Failed</h3>
          <p className="text-sm text-red-700 mt-1">{backtest.error_message}</p>
        </div>
      )}

      {/* Tabs */}
      {backtest.status === 'COMPLETED' && (
        <>
          <div className="border-b border-gray-200 mb-6">
            <nav className="-mb-px flex space-x-8">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm ${
                    activeTab === tab.key
                      ? 'border-blue-500 text-blue-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </nav>
          </div>

          {activeTab === 'results' && <BacktestMetrics backtest={backtest} />}
          {activeTab === 'equity' && <EquityCurve data={backtest.equity_curve} />}
          {activeTab === 'trades' && <TradesTable trades={backtest.trades} />}
          {activeTab === 'flow' && <DecisionFlow />}
        </>
      )}

      {/* Running state with refresh */}
      {backtest.status === 'RUNNING' && (
        <div className="text-center py-8">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-4" />
          <p className="text-gray-500">Backtest is running…</p>
          <button
            onClick={load}
            className="mt-4 text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            Refresh Status
          </button>
        </div>
      )}
    </div>
  );
}
