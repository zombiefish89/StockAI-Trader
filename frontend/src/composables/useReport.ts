import { ref } from "vue";
import type { StockAIReport } from "../types/report";
import { analyzeOne } from "../services/api";
import { normalizeReport } from "../utils/normalizeReport";

export function useReport() {
  const report = ref<StockAIReport | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

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
      report.value = normalizeReport(raw);
    } catch (err) {
      report.value = null;
      error.value =
        err instanceof Error ? err.message : "获取分析报告失败，请稍后再试。";
    } finally {
      loading.value = false;
    }
  }

  return {
    report,
    loading,
    error,
    load,
  };
}
