import type { SystemStatus, HealthResponse } from '@/types/api';
import { apiGet } from './client';

export async function getSystemStatus(): Promise<SystemStatus> {
  return apiGet<SystemStatus>('/api/v1/system/status');
}

export async function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>('/health');
}
