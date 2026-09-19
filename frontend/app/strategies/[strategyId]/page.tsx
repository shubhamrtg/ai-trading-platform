'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { getStrategy } from '@/lib/api';
import type { StrategyDetail } from '@/types/api';
import LoadingState from '@/components/ui/LoadingState';
import ErrorState from '@/components/ui/ErrorState';
import StatusBadge from '@/components/ui/StatusBadge';
import { formatDateTime } from '@/lib/utils';

export default function StrategyDetailPage() {
  const params = useParams();
  const strategyId = params.strategyId as string;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [strategy, setStrategy] = useState<StrategyDetail | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    getStrategy(strategyId)
      .then(setStrategy)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [strategyId]);

  if (loading) return <LoadingState message="Loading strategy…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!strategy) return <ErrorState title="Strategy not found" />;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{strategy.name}</h1>
        <div className="flex items-center gap-3 mt-2">
          <span className="text-sm text-gray-500">{strategy.strategy_id}</span>
          <StatusBadge status={strategy.status} />
        </div>
        {strategy.description && (
          <p className="mt-2 text-gray-600">{strategy.description}</p>
        )}
        {strategy.author && (
          <p className="mt-1 text-sm text-gray-400">Author: {strategy.author}</p>
        )}
      </div>

      <h2 className="text-lg font-semibold text-gray-900 mb-4">Versions</h2>
      {strategy.versions.length === 0 ? (
        <p className="text-gray-500">No versions registered.</p>
      ) : (
        <div className="space-y-4">
          {strategy.versions.map((v) => (
            <div key={v.id} className="bg-white shadow rounded-lg p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-medium text-gray-900">v{v.version}</h3>
                <StatusBadge status={v.status} />
              </div>
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-sm">
                {v.source_hash && (
                  <>
                    <dt className="text-gray-500">Source Hash</dt>
                    <dd className="text-gray-900 font-mono text-xs">{v.source_hash}</dd>
                  </>
                )}
                {v.supported_timeframes.length > 0 && (
                  <>
                    <dt className="text-gray-500">Supported Timeframes</dt>
                    <dd className="text-gray-900">{v.supported_timeframes.join(', ')}</dd>
                  </>
                )}
                {v.supported_asset_classes.length > 0 && (
                  <>
                    <dt className="text-gray-500">Asset Classes</dt>
                    <dd className="text-gray-900">{v.supported_asset_classes.join(', ')}</dd>
                  </>
                )}
                {v.required_indicators.length > 0 && (
                  <>
                    <dt className="text-gray-500">Required Indicators</dt>
                    <dd className="text-gray-900">{v.required_indicators.join(', ')}</dd>
                  </>
                )}
                {v.created_at && (
                  <>
                    <dt className="text-gray-500">Created</dt>
                    <dd className="text-gray-900">{formatDateTime(v.created_at)}</dd>
                  </>
                )}
                {v.updated_at && (
                  <>
                    <dt className="text-gray-500">Updated</dt>
                    <dd className="text-gray-900">{formatDateTime(v.updated_at)}</dd>
                  </>
                )}
              </dl>
              {Object.keys(v.parameters_schema).length > 0 && (
                <div className="mt-3">
                  <p className="text-sm text-gray-500 mb-1">Parameters Schema</p>
                  <pre className="bg-gray-50 p-3 rounded text-xs overflow-x-auto">
                    {JSON.stringify(v.parameters_schema, null, 2)}
                  </pre>
                </div>
              )}
              <p className="mt-2 text-xs text-gray-400 italic">
                Strategy version fields are immutable once the version leaves DRAFT status.
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
