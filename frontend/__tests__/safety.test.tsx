import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import SimulationBanner from '@/components/Layout/SimulationBanner';
import DecisionFlow from '@/components/Backtests/DecisionFlow';

describe('Safety Verification', () => {
  it('simulation banner warns about no real trading', () => {
    const { container } = render(<SimulationBanner />);
    const text = container.textContent || '';
    expect(text).toContain('SIMULATION');
    expect(text).not.toContain('Place Order');
    expect(text).not.toContain('Buy');
    expect(text).not.toContain('Sell');
    expect(text).not.toContain('Execute Live');
  });

  it('decision flow does not contain live trading actions', () => {
    const { container } = render(<DecisionFlow />);
    const text = container.textContent || '';
    expect(text).not.toContain('Place Order');
    expect(text).not.toContain('Execute Live');
    expect(text).not.toContain('Enable Live Trading');
    expect(text).toContain('simulation-only');
  });
});
