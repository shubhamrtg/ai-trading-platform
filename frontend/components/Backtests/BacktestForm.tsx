'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import type { BacktestCreateRequest, StrategyListItem, StrategyDetail, StrategyVersion } from '@/types/api';
import { createBacktest } from '@/lib/api/backtests';
import { getStrategy } from '@/lib/api/strategies';
import { ApiError } from '@/lib/api/client';

export default function BacktestForm({
  strategies,
}: {
  strategies: StrategyListItem[];
}) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedStrategy, setSelectedStrategy] = useState<StrategyDetail | null>(null);
  const [loadingStrategy, setLoadingStrategy] = useState(false);

  const [formData, setFormData] = useState({
    strategy_id: '',
    strategy_version: '',
    symbol: '',
    timeframe: '',
    start_time: '',
    end_time: '',
    initial_capital: '100000',
    commission_pct: '0',
    slippage_pct: '0',
  });

  const [parameters, setParameters] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!formData.strategy_id) {
      setSelectedStrategy(null);
      setFormData(prev => ({ ...prev, strategy_version: '', timeframe: '' }));
      setParameters({});
      return;
    }

    setLoadingStrategy(true);
    getStrategy(formData.strategy_id)
      .then(detail => {
        setSelectedStrategy(detail);
        const activeVersions = detail.versions.filter(v => v.status === 'ACTIVE');
        const firstActive = activeVersions.length > 0 ? activeVersions[0] : undefined;
        
        setFormData(prev => {
          let newTimeframe = prev.timeframe;
          if (firstActive) {
            if (firstActive.supported_timeframes.length === 0) {
              newTimeframe = '';
            } else if (!firstActive.supported_timeframes.includes(prev.timeframe)) {
              newTimeframe = firstActive.supported_timeframes[0];
            }
          } else {
            newTimeframe = '';
          }
          return { 
            ...prev, 
            strategy_version: firstActive?.version || '',
            timeframe: newTimeframe
          };
        });
      })
      .catch(err => {
        console.error(err);
        setError('Failed to load strategy details.');
      })
      .finally(() => {
        setLoadingStrategy(false);
      });
  }, [formData.strategy_id]);

  const selectedVersion: StrategyVersion | undefined = selectedStrategy?.versions.find(
    v => v.version === formData.strategy_version
  );

  // Timeframe consistency when version changes manually
  useEffect(() => {
    if (selectedVersion) {
      setFormData(prev => {
        if (selectedVersion.supported_timeframes.length === 0) {
          if (prev.timeframe !== '') return { ...prev, timeframe: '' };
        } else if (!selectedVersion.supported_timeframes.includes(prev.timeframe)) {
          return { ...prev, timeframe: selectedVersion.supported_timeframes[0] };
        }
        return prev;
      });
    }
  }, [selectedVersion]);

  // Initialize parameters when version changes
  useEffect(() => {
    if (selectedVersion?.parameters_schema) {
      const initialParams: Record<string, string> = {};
      const schema = selectedVersion.parameters_schema;
      
      if (schema.properties) {
        const props = schema.properties as Record<string, any>;
        Object.keys(props).forEach(key => {
          initialParams[key] = props[key].default !== undefined ? String(props[key].default) : '';
        });
      } else {
        Object.keys(schema).forEach(key => {
          initialParams[key] = String(schema[key]);
        });
      }
      setParameters(initialParams);
    } else {
      setParameters({});
    }
  }, [selectedVersion]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setFormData((prev) => ({ ...prev, [e.target.name]: e.target.value }));
    setError(null);
  };

  const handleParameterChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    const checked = (e.target as HTMLInputElement).checked;
    setParameters(prev => ({ 
      ...prev, 
      [name]: type === 'checkbox' ? String(checked) : value 
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!formData.strategy_id || !formData.strategy_version || !formData.symbol || !formData.timeframe) {
      setError('Please fill in all required fields.');
      return;
    }

    if (!selectedVersion || !selectedVersion.supported_timeframes.includes(formData.timeframe)) {
      setError('Selected timeframe is not supported by the selected strategy version.');
      return;
    }

    if (new Date(formData.start_time) >= new Date(formData.end_time)) {
      setError('Start date must be before end date.');
      return;
    }

    setIsSubmitting(true);

    try {
      const parsedParameters: Record<string, any> = {};
      Object.entries(parameters).forEach(([k, v]) => {
        if (v === 'true') parsedParameters[k] = true;
        else if (v === 'false') parsedParameters[k] = false;
        else if (!isNaN(Number(v)) && v.trim() !== '') parsedParameters[k] = Number(v);
        else parsedParameters[k] = v;
      });

      const request: BacktestCreateRequest = {
        strategy_id: formData.strategy_id,
        strategy_version: formData.strategy_version,
        symbol: formData.symbol.toUpperCase(),
        timeframe: formData.timeframe,
        start_time: new Date(formData.start_time).toISOString(),
        end_time: new Date(formData.end_time).toISOString(),
        initial_capital: parseFloat(formData.initial_capital),
        commission_pct: parseFloat(formData.commission_pct) || 0,
        slippage_pct: parseFloat(formData.slippage_pct) || 0,
      };

      if (Object.keys(parsedParameters).length > 0) {
        request.parameters = parsedParameters;
      }

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

  const renderParameterInputs = () => {
    if (!selectedVersion?.parameters_schema) return null;
    const schema = selectedVersion.parameters_schema;
    let fields: Array<{name: string, type: string, description?: string, required?: boolean, min?: number, max?: number, enum?: any[]}> = [];

    if (schema.properties) {
      const props = schema.properties as Record<string, any>;
      fields = Object.keys(props).map(k => {
        const p = props[k];
        let min = p.minimum !== undefined ? p.minimum : p.exclusiveMinimum !== undefined ? p.exclusiveMinimum + (p.type === 'integer' ? 1 : 0.000001) : undefined;
        let max = p.maximum !== undefined ? p.maximum : p.exclusiveMaximum !== undefined ? p.exclusiveMaximum - (p.type === 'integer' ? 1 : 0.000001) : undefined;
        return {
          name: k,
          type: p.type === 'integer' || p.type === 'number' ? 'number' : p.type === 'boolean' ? 'checkbox' : 'text',
          description: p.description,
          required: schema.required ? schema.required.includes(k) : false,
          min: min,
          max: max,
          enum: p.enum,
        };
      });
    } else {
      fields = Object.keys(schema).map(k => ({
        name: k,
        type: typeof schema[k] === 'number' ? 'number' : typeof schema[k] === 'boolean' ? 'checkbox' : 'text',
        required: true,
      }));
    }

    if (fields.length === 0) return null;

    return (
      <div className="bg-gray-50 p-4 rounded-md border border-gray-200 space-y-4">
        <h3 className="font-medium text-sm text-gray-900 border-b pb-2">Strategy Parameters</h3>
        <div className="grid grid-cols-2 gap-4">
          {fields.map(field => (
            <div key={field.name}>
              <label className="block text-sm font-medium text-gray-700">
                {field.name} {field.required && '*'}
              </label>
              {field.enum ? (
                <select
                  name={field.name}
                  value={parameters[field.name] || ''}
                  onChange={handleParameterChange}
                  required={field.required}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
                >
                  <option value="">Select...</option>
                  {field.enum.map(opt => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              ) : field.type === 'checkbox' ? (
                <input
                  type="checkbox"
                  name={field.name}
                  checked={parameters[field.name] === 'true'}
                  onChange={handleParameterChange}
                  className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                />
              ) : (
                <input
                  type={field.type}
                  name={field.name}
                  value={parameters[field.name] || ''}
                  onChange={handleParameterChange}
                  step={field.type === 'number' ? 'any' : undefined}
                  min={field.min}
                  max={field.max}
                  required={field.required}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
                />
              )}
              {field.description && (
                <p className="mt-1 text-xs text-gray-500">{field.description}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  };

  const activeVersions = selectedStrategy?.versions.filter(v => v.status === 'ACTIVE') || [];

  return (
    <form onSubmit={handleSubmit} className="bg-white shadow rounded-lg p-6 max-w-2xl">
      <h2 className="text-xl font-semibold mb-6">Create New Backtest</h2>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="space-y-6">
        {/* Strategy Selection */}
        <div className="grid grid-cols-2 gap-4">
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
            <label htmlFor="strategy_version" className="block text-sm font-medium text-gray-700">
              Version {loadingStrategy && <span className="text-gray-400 text-xs ml-2">Loading…</span>}
            </label>
            <select
              id="strategy_version"
              name="strategy_version"
              value={formData.strategy_version}
              onChange={handleChange}
              disabled={!selectedStrategy || activeVersions.length === 0}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2 disabled:bg-gray-100"
              required
            >
              <option value="">Select a version…</option>
              {activeVersions.map((v) => (
                <option key={v.version} value={v.version}>
                  {v.version} ({v.status})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Dynamic Parameters */}
        {renderParameterInputs()}

        {/* Backtest Configuration */}
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
              disabled={!selectedVersion || selectedVersion.supported_timeframes.length === 0}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2 disabled:bg-gray-100"
              required
            >
              <option value="">Select timeframe…</option>
              {selectedVersion?.supported_timeframes.map(tf => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
            {selectedVersion && selectedVersion.supported_timeframes.length === 0 && (
              <p className="text-xs text-amber-600 mt-1">Warning: Strategy version has no supported timeframes.</p>
            )}
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

      <div className="mt-8 pt-4 border-t border-gray-200 flex justify-end gap-3">
        <button
          type="button"
          onClick={() => router.back()}
          className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isSubmitting || !selectedVersion || selectedVersion.status !== 'ACTIVE'}
          className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
        >
          {isSubmitting ? 'Running Backtest…' : 'Run Backtest'}
        </button>
      </div>
    </form>
  );
}
