'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import type { BacktestCreateRequest, StrategyListItem } from '@/types/api';
import { createBacktest } from '@/lib/api/backtests';
import { ApiError } from '@/lib/api/client';

export default function BacktestForm({
  strategies,
}: {
  strategies: StrategyListItem[];
}) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    strategy_id: '',
    strategy_version: '',
    symbol: '',
    timeframe: '1h',
    start_time: '',
    end_time: '',
    initial_capital: '100000',
    commission_pct: '0',
    slippage_pct: '0',
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setFormData((prev) => ({ ...prev, [e.target.name]: e.target.value }));
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Basic client-side validation
    if (!formData.strategy_id) {
      setError('Strategy is required.');
      return;
    }
    if (!formData.strategy_version) {
      setError('Strategy version is required.');
      return;
    }
    if (!formData.symbol) {
      setError('Symbol is required.');
      return;
    }
    if (!formData.start_time || !formData.end_time) {
      setError('Start and end dates are required.');
      return;
    }
    if (new Date(formData.start_time) >= new Date(formData.end_time)) {
      setError('Start date must be before end date.');
      return;
    }
    const capital = parseFloat(formData.initial_capital);
    if (isNaN(capital) || capital <= 0) {
      setError('Initial capital must be a positive number.');
      return;
    }

    setIsSubmitting(true);

    try {
      const request: BacktestCreateRequest = {
        strategy_id: formData.strategy_id,
        strategy_version: formData.strategy_version,
        symbol: formData.symbol.toUpperCase(),
        timeframe: formData.timeframe,
        start_time: new Date(formData.start_time).toISOString(),
        end_time: new Date(formData.end_time).toISOString(),
        initial_capital: capital,
        commission_pct: parseFloat(formData.commission_pct) || 0,
        slippage_pct: parseFloat(formData.slippage_pct) || 0,
      };

      const result = await createBacktest(request);
      router.push(`/backtests/${result.run_id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      } else {
        setError('An unexpected error occurred.');
      }
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-white shadow rounded-lg p-6 max-w-2xl">
      <h2 className="text-xl font-semibold mb-6">Create New Backtest</h2>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="space-y-4">
        <div>
          <label htmlFor="strategy_id" className="block text-sm font-medium text-gray-700">Strategy</label>
          <select
            id="strategy_id"
            name="strategy_id"
            value={formData.strategy_id}
            onChange={handleChange}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
            required
          >
            <option value="">Select a strategy…</option>
            {strategies.map((s) => (
              <option key={s.strategy_id} value={s.strategy_id}>
                {s.name} ({s.strategy_id})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="strategy_version" className="block text-sm font-medium text-gray-700">Version</label>
          <input
            type="text"
            id="strategy_version"
            name="strategy_version"
            value={formData.strategy_version}
            onChange={handleChange}
            placeholder="e.g., 1.0.0"
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
            required
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="symbol" className="block text-sm font-medium text-gray-700">Symbol</label>
            <input
              type="text"
              id="symbol"
              name="symbol"
              value={formData.symbol}
              onChange={handleChange}
              placeholder="e.g., BTC-USD"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
              required
            />
          </div>
          <div>
            <label htmlFor="timeframe" className="block text-sm font-medium text-gray-700">Timeframe</label>
            <select
              id="timeframe"
              name="timeframe"
              value={formData.timeframe}
              onChange={handleChange}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
            >
              <option value="1m">1 Minute</option>
              <option value="5m">5 Minutes</option>
              <option value="15m">15 Minutes</option>
              <option value="1h">1 Hour</option>
              <option value="4h">4 Hours</option>
              <option value="1d">1 Day</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="start_time" className="block text-sm font-medium text-gray-700">Start Date</label>
            <input
              type="datetime-local"
              id="start_time"
              name="start_time"
              value={formData.start_time}
              onChange={handleChange}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
              required
            />
          </div>
          <div>
            <label htmlFor="end_time" className="block text-sm font-medium text-gray-700">End Date</label>
            <input
              type="datetime-local"
              id="end_time"
              name="end_time"
              value={formData.end_time}
              onChange={handleChange}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
              required
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label htmlFor="initial_capital" className="block text-sm font-medium text-gray-700">Initial Capital ($)</label>
            <input
              type="number"
              id="initial_capital"
              name="initial_capital"
              value={formData.initial_capital}
              onChange={handleChange}
              min="1"
              step="0.01"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
              required
            />
          </div>
          <div>
            <label htmlFor="commission_pct" className="block text-sm font-medium text-gray-700">Commission (%)</label>
            <input
              type="number"
              id="commission_pct"
              name="commission_pct"
              value={formData.commission_pct}
              onChange={handleChange}
              min="0"
              step="0.001"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
            />
          </div>
          <div>
            <label htmlFor="slippage_pct" className="block text-sm font-medium text-gray-700">Slippage (%)</label>
            <input
              type="number"
              id="slippage_pct"
              name="slippage_pct"
              value={formData.slippage_pct}
              onChange={handleChange}
              min="0"
              step="0.001"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
            />
          </div>
        </div>
      </div>

      <div className="mt-6">
        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full bg-blue-600 text-white py-2 px-4 rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed font-medium"
        >
          {isSubmitting ? 'Running Backtest…' : 'Run Backtest'}
        </button>
      </div>
    </form>
  );
}
