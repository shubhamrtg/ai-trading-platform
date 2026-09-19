import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import TradesTable from '@/components/Backtests/TradesTable';

describe('TradesTable', () => {
  it('shows empty state when no trades', () => {
    render(<TradesTable trades={[]} />);
    expect(screen.getByText('No trades')).toBeInTheDocument();
  });

  it('shows simulation warning label', () => {
    const trades = [
      {
        trade_sequence: 1,
        strategy_id: 'test',
        strategy_version: '1.0',
        symbol: 'BTC-USD',
        side: 'BUY' as const,
        quantity: '1.0',
        entry_timestamp: '2024-01-01T00:00:00Z',
        entry_price: '50000',
        exit_timestamp: '2024-01-02T00:00:00Z',
        exit_price: '51000',
        gross_pnl: '1000',
        fees: '10',
        slippage: '5',
        net_pnl: '990',
        return_percentage: '0.02',
      },
    ];
    render(<TradesTable trades={trades} />);
    expect(screen.getByText(/simulated trades/i)).toBeInTheDocument();
  });
});
