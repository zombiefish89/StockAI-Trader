import type { ScenarioRow, StockAIReport, TradingPlan, Verdict } from "../types/report";

const ALLOWED_VERDICTS: Verdict[] = ["HOLD", "BUY_THE_DIP", "TRIM", "SELL"];

function cloneReport(report: StockAIReport): StockAIReport {
  return JSON.parse(JSON.stringify(report)) as StockAIReport;
}

function roundValue(value?: number | null): number | null {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  return Number(value.toFixed(2));
}

function normalizePlan(plan: TradingPlan | null, confidence: number): TradingPlan | null {
  if (!plan) return null;

  const normalized: TradingPlan = {
    ...plan,
    entry: roundValue(plan.entry),
    stop: roundValue(plan.stop),
    targets: plan.targets
      ?.map((value) => roundValue(value) ?? undefined)
      .filter((value): value is number => value !== null && value !== undefined),
  };

  if (plan.entryRange) {
    normalized.entryRange = {
      min: roundValue(plan.entryRange.min),
      max: roundValue(plan.entryRange.max),
      note: plan.entryRange.note ?? null,
    };
  }

  if (confidence < 0.55) {
    normalized.entry = null;
  }

  return normalized;
}

function normalizeScenarios(rows: ScenarioRow[]): ScenarioRow[] {
  return rows.map((row) => {
    const probability =
      typeof row.probability === "number" && !Number.isNaN(row.probability)
        ? Number((row.probability > 1 ? row.probability / 100 : row.probability).toFixed(2))
        : null;
    return {
      ...row,
      probability,
      target: roundValue(row.target),
    };
  });
}

function ensureNarrative(text?: string | null): string {
  const cleaned = (text ?? "").trim();
  return cleaned || "分析内容暂缺，请结合最新行情自行评估。";
}

export function normalizeReport(report: StockAIReport): StockAIReport {
  const normalized = cloneReport(report);

  normalized.metadata = {
    dataSource: normalized.metadata?.dataSource ?? null,
    modelVersion: normalized.metadata?.modelVersion ?? null,
    latencyMs: normalized.metadata?.latencyMs ?? null,
  };

  const rawConfidence = Number(normalized.verdict.confidence);
  normalized.verdict.confidence = Number.isFinite(rawConfidence)
    ? Math.min(1, Math.max(0, rawConfidence))
    : 0;

  const riskList = Array.isArray(normalized.riskNotes) ? normalized.riskNotes : [];
  normalized.riskNotes = riskList.filter(
    (note): note is string => typeof note === "string" && note.trim().length > 0
  );

  normalized.analysisNarrative = ensureNarrative(normalized.analysisNarrative);

  const decision = normalized.verdict.decision;
  if (!ALLOWED_VERDICTS.includes(decision)) {
    normalized.verdict.decision = "BUY_THE_DIP";
  }
  if (decision === "BUY") {
    normalized.verdict.decision = "BUY_THE_DIP";
  }

  if (normalized.verdict.decision === "HOLD") {
    normalized.plan = null;
  } else {
    normalized.plan = normalizePlan(normalized.plan, normalized.verdict.confidence);
  }

  const scenarioList = Array.isArray(normalized.scenarios) ? normalized.scenarios : [];
  normalized.scenarios = normalizeScenarios(scenarioList);

  return normalized;
}
