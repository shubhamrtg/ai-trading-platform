// Strategy types
export interface StrategyListItem {
  id: number;
  strategy_id: string;
  name: string;
  description: string | null;
  author: string | null;
  status: 'DRAFT' | 'ACTIVE' | 'DEPRECATED' | 'DISABLED';
  version_count: number;
}

export interface StrategyVersion {
  id: number;
  version: string;
  status: 'DRAFT' | 'ACTIVE' | 'DEPRECATED' | 'DISABLED';
  source_hash: string | null;
  supported_asset_classes: string[];
  supported_timeframes: string[];
  required_indicators: string[];
  parameters_schema: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

export interface StrategyDetail {
  id: number;
  strategy_id: string;
  name: string;
  description: string | null;
  author: string | null;
  status: 'DRAFT' | 'ACTIVE' | 'DEPRECATED' | 'DISABLED';
  versions: StrategyVersion[];
}

// Backtest types
export interface BacktestListItem {
  run_id: string;
  status: 'CREATED' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  strategy_id: string;
  strategy_version: string;
  symbol: string;
  timeframe: string;
  start_time: string;
  end_time: string;
  created_at: string;
  completed_at: string | null;
  final_equity: string | null;
  total_return_pct: string | null;
  realized_pnl: string | null;
  total_trades: number | null;
}

export interface BacktestTradeRecord {
  trade_sequence: number;
  strategy_id: string;
  strategy_version: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: string;
  entry_timestamp: string;
  entry_price: string;
  exit_timestamp: string;
  exit_price: string;
  gross_pnl: string;
  fees: string;
  slippage: string;
  net_pnl: string;
  return_percentage: string;
}

export interface BacktestEquityPoint {
  timestamp: string;
  cash: string;
  position_value: string;
  equity: string;
  drawdown_pct: string;
}

export interface BacktestDetail extends BacktestListItem {
  initial_capital: string;
  commission_pct: string;
  slippage_pct: string;
  parameters: Record<string, unknown>;
  unrealized_pnl: string | null;
  winning_trades: number | null;
  losing_trades: number | null;
  win_rate: string | null;
  max_drawdown_pct: string | null;
  peak_equity: string | null;
  minimum_equity: string | null;
  average_win: string | null;
  average_loss: string | null;
  largest_win: string | null;
  largest_loss: string | null;
  error_message: string | null;
  trades: BacktestTradeRecord[];
  equity_curve: BacktestEquityPoint[];
}

export interface BacktestCreateRequest {
  strategy_id: string;
  strategy_version: string;
  symbol: string;
  timeframe: string;
  start_time: string;
  end_time: string;
  initial_capital?: number;
  commission_pct?: number;
  slippage_pct?: number;
  parameters?: Record<string, unknown>;
  idempotency_key?: string;
}

export interface BacktestListPaginated {
  items: BacktestListItem[];
  total: number;
}

// System types
export interface SystemStatus {
  app_name: string;
  version: string;
  trading_mode: string;
  debug: boolean;
  uptime_seconds: number;
  configuration_valid: boolean;
  timestamp: string;
}

export interface ComponentHealth {
  status: 'healthy' | 'unhealthy' | 'unavailable';
  details: string | null;
}

export interface HealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy';
  version: string;
  trading_mode: string;
  components: Record<string, ComponentHealth>;
  timestamp: string;
}
