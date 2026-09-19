import { describe, it, expect } from 'vitest';
import { formatDecimal, formatPercent, formatCurrency, formatDateTime, pnlColor } from '@/lib/utils';

describe('utils', () => {
  describe('formatDecimal', () => {
    it('formats a number', () => {
      expect(formatDecimal(1234.5678, 2)).toBe('1,234.57');
    });

    it('returns dash for null', () => {
      expect(formatDecimal(null)).toBe('—');
    });

    it('handles string input', () => {
      expect(formatDecimal('42.5', 1)).toBe('42.5');
    });
  });

  describe('formatPercent', () => {
    it('formats as percent', () => {
      expect(formatPercent('0.05')).toBe('5.00%');
    });

    it('returns dash for null', () => {
      expect(formatPercent(null)).toBe('—');
    });
  });

  describe('formatCurrency', () => {
    it('formats with dollar sign', () => {
      expect(formatCurrency('1000.5')).toBe('$1,000.50');
    });
  });

  describe('pnlColor', () => {
    it('returns green for positive', () => {
      expect(pnlColor('100')).toBe('text-green-600');
    });
    it('returns red for negative', () => {
      expect(pnlColor('-50')).toBe('text-red-600');
    });
    it('returns gray for null', () => {
      expect(pnlColor(null)).toBe('text-gray-500');
    });
  });
});
