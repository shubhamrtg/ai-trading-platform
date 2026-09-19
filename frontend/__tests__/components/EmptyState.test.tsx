import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import EmptyState from '@/components/ui/EmptyState';

describe('EmptyState', () => {
  it('renders the title', () => {
    render(<EmptyState title="No data" />);
    expect(screen.getByText('No data')).toBeInTheDocument();
  });

  it('renders an optional message', () => {
    render(<EmptyState title="No data" message="Try again later" />);
    expect(screen.getByText('Try again later')).toBeInTheDocument();
  });
});
