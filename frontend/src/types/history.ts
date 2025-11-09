import type { StockAIReport } from "./report";

export interface AnalysisHistoryRecord {
  id: string;
  ticker: string;
  timeframe: string;
  asOf: string;
  createdAt: string;
  report: StockAIReport;
  context?: Record<string, unknown> | null;
}
