'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getStrategies } from '@/lib/api';
import type { StrategyListItem } from '@/types/api';
import LoadingState from '@/components/ui/LoadingState';
import ErrorState from '@/components/ui/ErrorState';
import EmptyState from '@/components/ui/EmptyState';
import StatusBadge from '@/components/ui/StatusBadge';

export default function StrategiesPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [strategies, setStrategies] = useState<StrategyListItem[]>([]);

  const load = () => {
    setLoading(true);
    setError(null);
    getStrategies()
      .then(setStrategies)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <LoadingState message="Loading strategies…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (strategies.length === 0) {
    return <EmptyState title="No strategies found" message="No trading strategies have been registered yet." />;
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Strategies</h1>
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Versions</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {strategies.map((s) => (
              <tr key={s.strategy_id} className="hover:bg-gray-50">
                <td className="px-6 py-4 whitespace-nowrap">
                  <Link href={`/strategies/${s.strategy_id}`} className="text-sm font-medium text-blue-600 hover:text-blue-800">
                    {s.strategy_id}
                  </Link>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{s.name}</td>
                <td className="px-6 py-4 whitespace-nowrap"><StatusBadge status={s.status} /></td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{s.version_count}</td>
                <td className="px-6 py-4 text-sm text-gray-500 max-w-xs truncate">{s.description ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
