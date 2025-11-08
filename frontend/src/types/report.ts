export type Verdict = "HOLD" | "BUY" | "BUY_THE_DIP" | "TRIM" | "SELL";

export interface VerdictInfo {
  decision: Verdict;
  confidence: number;
  headline: string;
  thesis: string;
}

export interface ReportMetadata {
  dataSource?: string | null;
  modelVersion?: string | null;
  latencyMs?: number | null;
}

export interface PlanRange {
  min?: number | null;
  max?: number | null;
  note?: string | null;
}

export interface TradingPlan {
  size?: string | null;
  entry?: number | null;
  entryRange?: PlanRange | null;
  trigger?: string | null;
  stop?: number | null;
  stopNote?: string | null;
  targets?: number[];
  targetNote?: string | null;
  notes?: string | null;
}

export interface ScenarioRow {
  name: string;
  probability?: number | null;
  trigger?: string | null;
  target?: number | null;
  action?: string | null;
}

export interface StockAIReport {
  ticker: string;
  timeframe: string;
  asOf: string;
  verdict: VerdictInfo;
  metadata: ReportMetadata;
  plan: TradingPlan | null;
  scenarios: ScenarioRow[];
  riskNotes: string[];
  analysisNarrative: string;
}
