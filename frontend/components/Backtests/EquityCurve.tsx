'use client';

import type { BacktestEquityPoint } from '@/types/api';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import EmptyState from '@/components/ui/EmptyState';

export default function EquityCurve({
  data,
  timeframe,
}: {
  data: BacktestEquityPoint[];
  timeframe?: string;
}) {
  if (!data || data.length === 0) {
    return <EmptyState title="No equity curve data" message="No equity data is available for this backtest." />;
  }

  const isIntraday = timeframe ? ['m', 'h'].some(unit => timeframe.includes(unit)) : false;

  const chartData = data.map((point) => {
    const d = new Date(point.timestamp);
    const timestampStr = isIntraday 
      ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

    return {
      timestamp: timestampStr,
      equity: parseFloat(point.equity),
      drawdown: parseFloat(point.drawdown_pct) * 100,
    };
  });

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold mb-4">Equity Curve</h3>
      <ResponsiveContainer width="100%" height={400}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="timestamp" tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip
            formatter={(value: number, name: string) => [
              name === 'equity' ? `$${value.toLocaleString()}` : `${value.toFixed(2)}%`,
              name === 'equity' ? 'Equity' : 'Drawdown',
            ]}
          />
          <Line type="monotone" dataKey="equity" stroke="#2563eb" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
