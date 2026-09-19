import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DashboardPage from '../app/page';
import BacktestForm from '../components/Backtests/BacktestForm';
import * as api from '../lib/api';

// Mock Next.js router
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useParams: () => ({ runId: '123' }),
}));

// Mock API calls
vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal() as any;
  return {
    ...actual,
    getSystemStatus: vi.fn(),
    getHealth: vi.fn(),
    getStrategies: vi.fn(),
    getBacktests: vi.fn(),
    getStrategy: vi.fn(),
    createBacktest: vi.fn(),
  };
});

describe('Dashboard Integration Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('API returns [] -> empty state (No backtests yet, No strategies registered)', async () => {
    vi.mocked(api.getSystemStatus).mockResolvedValue({
      app_name: 'test', version: '1.0', trading_mode: 'BACKTEST', debug: false, uptime_seconds: 100, configuration_valid: true, timestamp: ''
    });
    vi.mocked(api.getHealth).mockResolvedValue({
      status: 'healthy', version: '1.0', trading_mode: 'BACKTEST', components: {}, timestamp: ''
    });
    vi.mocked(api.getStrategies).mockResolvedValue([]);
    vi.mocked(api.getBacktests).mockResolvedValue({ items: [], total: 0 });

    render(<DashboardPage />);
    
    await waitFor(() => {
      expect(screen.queryByText('Loading dashboard…')).not.toBeInTheDocument();
    });

    // Check for empty states
    expect(screen.getByText('No strategies registered.')).toBeInTheDocument();
    expect(screen.getByText('No backtests yet.')).toBeInTheDocument();
    // System health check
    expect(screen.getByText('Healthy')).toBeInTheDocument();
  });

  it('API throws / returns failure -> error state (not empty arrays)', async () => {
    vi.mocked(api.getSystemStatus).mockRejectedValue(new Error('API Failure'));
    vi.mocked(api.getHealth).mockRejectedValue(new Error('API Failure'));
    vi.mocked(api.getStrategies).mockRejectedValue(new Error('API Failure'));
    vi.mocked(api.getBacktests).mockRejectedValue(new Error('API Failure'));

    render(<DashboardPage />);
    
    await waitFor(() => {
      expect(screen.queryByText('Loading dashboard…')).not.toBeInTheDocument();
    });

    expect(screen.getByText(/Failed to load dashboard data/)).toBeInTheDocument();
    // Ensure we don't just show 'No strategies registered.' when it's an error
    expect(screen.queryByText('No strategies registered.')).not.toBeInTheDocument();
  });

  it('healthy -> Healthy, configuration invalid -> Config Invalid', async () => {
    vi.mocked(api.getSystemStatus).mockResolvedValue({
      app_name: 'test', version: '1.0', trading_mode: 'BACKTEST', debug: false, uptime_seconds: 100, configuration_valid: false, timestamp: ''
    });
    vi.mocked(api.getHealth).mockResolvedValue({
      status: 'degraded', version: '1.0', trading_mode: 'BACKTEST', components: {}, timestamp: ''
    });
    vi.mocked(api.getStrategies).mockResolvedValue([]);
    vi.mocked(api.getBacktests).mockResolvedValue({ items: [], total: 0 });

    render(<DashboardPage />);
    
    await waitFor(() => {
      expect(screen.queryByText('Loading dashboard…')).not.toBeInTheDocument();
    });

    // We check that health (Degraded) and config (Config Invalid) are presented
    expect(screen.getByText('Degraded')).toBeInTheDocument();
    expect(screen.getByText('Config Invalid')).toBeInTheDocument();
  });
});

describe('BacktestForm Integration Tests', () => {
  const mockStrategies = [
    { id: 1, strategy_id: 'strat_1', name: 'Strategy 1', description: '', author: '', status: 'ACTIVE' as const, version_count: 1 }
  ];

  const mockStrategyDetail = {
    id: 1, strategy_id: 'strat_1', name: 'Strategy 1', description: '', author: '', status: 'ACTIVE' as const,
    versions: [
      {
        id: 1, version: '1.0.0', status: 'ACTIVE' as const, source_hash: '', supported_asset_classes: [],
        supported_timeframes: ['1h', '4h'], required_indicators: [],
        parameters_schema: {
          properties: {
            fast_period: { type: 'integer', default: 10, description: 'Fast MA' },
            use_rsi: { type: 'boolean', default: false }
          },
          required: ['fast_period']
        },
        created_at: '', updated_at: ''
      }
    ]
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('strategy selected -> versions loaded -> timeframes & parameters displayed -> request contains parameters', async () => {
    vi.mocked(api.getStrategy).mockResolvedValue(mockStrategyDetail);
    vi.mocked(api.createBacktest).mockResolvedValue({ run_id: 'test-run-123' } as any);

    render(<BacktestForm strategies={mockStrategies} />);
    
    // Select strategy
    const strategySelect = screen.getByLabelText(/Strategy/i);
    fireEvent.change(strategySelect, { target: { value: 'strat_1' } });

    // Wait for version API call
    await waitFor(() => {
      expect(api.getStrategy).toHaveBeenCalledWith('strat_1');
    });

    // Check version is populated and selected
    const versionSelect = screen.getByLabelText(/Version/i) as HTMLSelectElement;
    expect(versionSelect.value).toBe('1.0.0');

    // Check timeframe options are restricted to 1h, 4h
    const timeframeSelect = screen.getByLabelText(/Timeframe/i) as HTMLSelectElement;
    expect(timeframeSelect.value).toBe('1h');
    const options = Array.from(timeframeSelect.options).map(o => o.value);
    expect(options).toContain('1h');
    expect(options).toContain('4h');
    expect(options).not.toContain('1d'); // Not in supported_timeframes

    // Check parameters are rendered
    expect(screen.getByText(/fast_period/i)).toBeInTheDocument();
    expect(screen.getByText(/use_rsi/i)).toBeInTheDocument();

    // Fill the rest of the form
    fireEvent.change(screen.getByLabelText(/Symbol/i), { target: { value: 'BTC-USD' } });
    fireEvent.change(screen.getByLabelText(/Start Date/i), { target: { value: '2023-01-01T00:00' } });
    fireEvent.change(screen.getByLabelText(/End Date/i), { target: { value: '2023-01-02T00:00' } });

    // Submit
    fireEvent.click(screen.getByText(/Run Backtest/i));

    await waitFor(() => {
      expect(api.createBacktest).toHaveBeenCalledWith(expect.objectContaining({
        strategy_id: 'strat_1',
        strategy_version: '1.0.0',
        symbol: 'BTC-USD',
        timeframe: '1h',
        parameters: {
          fast_period: 10,
          use_rsi: false
        }
      }));
    });
  });
});
