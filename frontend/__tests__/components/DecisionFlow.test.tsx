import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import DecisionFlow from '@/components/Backtests/DecisionFlow';

describe('DecisionFlow', () => {
  it('renders all pipeline stages', () => {
    render(<DecisionFlow />);
    expect(screen.getByText('Strategy')).toBeInTheDocument();
    expect(screen.getByText('Signal')).toBeInTheDocument();
    expect(screen.getByText('Risk Engine')).toBeInTheDocument();
    expect(screen.getByText('Risk Decision')).toBeInTheDocument();
    expect(screen.getByText('Order Intent')).toBeInTheDocument();
    expect(screen.getByText('Execution Engine')).toBeInTheDocument();
    expect(screen.getByText('Execution Result')).toBeInTheDocument();
  });

  it('renders architecture overview title', () => {
    render(<DecisionFlow />);
    expect(screen.getByText('Architecture Overview')).toBeInTheDocument();
    expect(screen.getByText(/This diagram shows the architectural pipeline/i)).toBeInTheDocument();
    expect(screen.getByText(/It is not a runtime execution record/i)).toBeInTheDocument();
  });

  it('indicates UI cannot initiate trades', () => {
    render(<DecisionFlow />);
    expect(screen.getByText(/UI cannot initiate trades/i)).toBeInTheDocument();
  });
});
