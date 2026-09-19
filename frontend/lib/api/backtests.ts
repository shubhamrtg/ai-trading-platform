import type {
  BacktestCreateRequest,
  BacktestDetail,
  BacktestListPaginated,
} from '@/types/api';
import { apiGet, apiPost } from './client';

export async function getBacktests(
  limit: number = 100,
  offset: number = 0,
): Promise<BacktestListPaginated> {
  return apiGet<BacktestListPaginated>(
    `/api/v1/backtests?limit=${limit}&offset=${offset}`,
  );
}

export async function getBacktest(runId: string): Promise<BacktestDetail> {
  return apiGet<BacktestDetail>(`/api/v1/backtests/${runId}`);
}

export async function createBacktest(
  request: BacktestCreateRequest,
): Promise<BacktestDetail> {
  return apiPost<BacktestDetail>('/api/v1/backtests', request);
}
