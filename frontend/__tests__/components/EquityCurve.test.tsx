import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import EquityCurve from '../../components/Backtests/EquityCurve';

// We mock recharts because it uses ResizeObserver and SVG elements which are hard to test in JSDOM
// Instead, we just want to verify how the data is transformed before being passed to Recharts.
vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal() as any;
  return {
    ...actual,
    ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
    LineChart: ({ data }: { data: any[] }) => (
      <div data-testid="chart-data">{JSON.stringify(data)}</div>
    ),
  };
});

describe('EquityCurve', () => {
  const mockData = [
    { timestamp: '2023-01-01T14:30:00Z', cash: '1000', position_value: '0', equity: '1000', drawdown_pct: '0' },
  ];

  it('renders correctly with intraday timeframe (preserves time)', () => {
    const { getByTestId } = render(<EquityCurve data={mockData} timeframe="1h" />);
    const dataStr = getByTestId('chart-data').textContent;
    const parsed = JSON.parse(dataStr!);
    
    // Check if the timestamp contains a colon (indicating time is preserved)
    // toLocaleDateString('en-US', { ... hour, minute }) outputs e.g., "Jan 1, 09:30 AM" or similar
    expect(parsed[0].timestamp).toMatch(/:/);
  });

  it('renders correctly with daily timeframe (date only)', () => {
    const { getByTestId } = render(<EquityCurve data={mockData} timeframe="1d" />);
    const dataStr = getByTestId('chart-data').textContent;
    const parsed = JSON.parse(dataStr!);
    
    // Daily shouldn't contain time (no colon)
    expect(parsed[0].timestamp).not.toMatch(/:/);
  });
});
