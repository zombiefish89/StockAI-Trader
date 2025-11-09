import { ref } from "vue";
import type { StockAIReport } from "../types/report";
import { analyzeOne } from "../services/api";
import { normalizeReport } from "../utils/normalizeReport";

export function useReport() {
  const report = ref<StockAIReport | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const CACHE_KEY = "stockai:last-analysis";

  async function load(symbol: string, timeframe = "1d") {
    if (!symbol) {
      report.value = null;
      error.value = null;
      loading.value = false;
      return;
    }

    loading.value = true;
    error.value = null;
    try {
      const raw = await analyzeOne(symbol, timeframe);
      const normalized = normalizeReport(raw);
      report.value = normalized;
      saveCache(symbol, timeframe, normalized);
    } catch (err) {
      report.value = null;
      error.value =
        err instanceof Error ? err.message : "获取分析报告失败，请稍后再试。";
    } finally {
      loading.value = false;
    }
  }

  function saveCache(symbol: string, timeframe: string, payload: StockAIReport) {
    try {
      const data = JSON.stringify({ symbol, timeframe, report: payload });
      window.sessionStorage.setItem(CACHE_KEY, data);
    } catch (err) {
      console.warn("failed to cache analysis", err);
    }
  }

  function loadFromCache(): { symbol: string; timeframe: string } | null {
    try {
      const raw = window.sessionStorage.getItem(CACHE_KEY);
      if (!raw) {
        return null;
      }
      const parsed = JSON.parse(raw) as {
        symbol: string;
        timeframe: string;
        report: StockAIReport;
      };
      if (parsed.report) {
        report.value = normalizeReport(parsed.report);
      }
      return {
        symbol: parsed.symbol || "",
        timeframe: parsed.timeframe || "1d",
      };
    } catch (err) {
      console.warn("failed to restore cached analysis", err);
      return null;
    }
  }

  return {
    report,
    loading,
    error,
    load,
    loadFromCache,
  };
}
