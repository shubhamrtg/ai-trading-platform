'use client';

import { useEffect, useState } from 'react';
import { getStrategies } from '@/lib/api';
import type { StrategyListItem } from '@/types/api';
import BacktestForm from '@/components/Backtests/BacktestForm';
import LoadingState from '@/components/ui/LoadingState';
import ErrorState from '@/components/ui/ErrorState';

export default function NewBacktestPage() {
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

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Create Backtest</h1>
      <BacktestForm strategies={strategies} />
    </div>
  );
}
