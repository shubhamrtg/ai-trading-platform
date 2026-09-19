import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import SimulationBanner from '@/components/Layout/SimulationBanner';

describe('SimulationBanner', () => {
  it('renders the simulation mode warning', () => {
    render(<SimulationBanner />);
    expect(screen.getByText(/SIMULATION/i)).toBeInTheDocument();
    expect(screen.getByText(/BACKTESTING MODE/i)).toBeInTheDocument();
  });

  it('indicates no real trading is active', () => {
    render(<SimulationBanner />);
    expect(screen.getByText(/No real trading/i)).toBeInTheDocument();
  });
});
