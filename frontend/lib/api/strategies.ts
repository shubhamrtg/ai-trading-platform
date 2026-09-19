import type { StrategyListItem, StrategyDetail } from '@/types/api';
import { apiGet } from './client';

export async function getStrategies(): Promise<StrategyListItem[]> {
  return apiGet<StrategyListItem[]>('/api/v1/strategies');
}

export async function getStrategy(strategyId: string): Promise<StrategyDetail> {
  return apiGet<StrategyDetail>(`/api/v1/strategies/${encodeURIComponent(strategyId)}`);
}
