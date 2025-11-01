<template>
  <main>
    <header>
      <h1>StockAI Trader</h1>
      <p class="tagline">
        1 分钟读懂行情，获取可执行的买卖建议
      </p>
    </header>

    <form class="form" @submit.prevent="analyze">
      <label>
        股票代码
        <input v-model="form.ticker" placeholder="例如 AAPL 或 600519.SS" required />
      </label>

      <label>
        时间粒度
        <select v-model="form.timeframe">
          <option value="1d">日线 · 中短线判断</option>
          <option value="1h">小时线 · 日内趋势</option>
          <option value="15m">15 分钟 · 短线节奏</option>
          <option value="5m">5 分钟 · 超短/高频观察</option>
        </select>
        <small class="helper">
          选择越短的周期，分析越敏感但噪音更高；若不确定，保持日线即可。
        </small>
      </label>

      <button type="submit" :disabled="loading">
        {{ loading ? "分析中..." : "生成分析" }}
      </button>
    </form>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="!loading && !result" class="placeholder">
      输入股票代码并点击生成分析，查看 AI 助手的建议。
    </p>

    <AnalysisResult v-if="result" :data="result" />

    <MacroOverview />
    <WatchlistManager />
    <OpportunityScanner />
    <DailyReportViewer />
  </main>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import axios from "axios";
import AnalysisResult, {
  AnalysisResultPayload,
} from "./components/AnalysisResult.vue";
import MacroOverview from "./components/MacroOverview.vue";
import WatchlistManager from "./components/WatchlistManager.vue";
import DailyReportViewer from "./components/DailyReportViewer.vue";
import OpportunityScanner from "./components/OpportunityScanner.vue";

interface AnalysisForm {
  ticker: string;
  timeframe: string;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

const form = reactive<AnalysisForm>({
  ticker: "AAPL",
  timeframe: "1d",
});

const loading = ref(false);
const error = ref("");
const result = ref<AnalysisResultPayload | null>(null);

async function analyze() {
  error.value = "";
  loading.value = true;
  try {
    const { data } = await axios.post<AnalysisResultPayload>(
      `${API_BASE}/analyze`,
      {
        ticker: form.ticker,
        timeframe: form.timeframe,
      }
    );
    result.value = data;
  } catch (err) {
    error.value =
      err instanceof Error
        ? err.message
        : "分析失败，请稍后重试或检查后端服务。";
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
main {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

header h1 {
  margin: 0;
  font-size: 2.25rem;
}

.tagline {
  color: #475569;
  margin: 0.25rem 0 1rem 0;
}

.form {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  background: #fff;
  padding: 1.25rem;
  border-radius: 12px;
  box-shadow: 0 10px 25px rgba(15, 23, 42, 0.06);
}

label {
  display: flex;
  flex-direction: column;
  font-weight: 600;
  gap: 0.5rem;
  color: #0f172a;
}

input,
select {
  border: 1px solid #cbd5f5;
  border-radius: 8px;
  padding: 0.6rem 0.75rem;
  font-size: 0.95rem;
}

.helper {
  font-size: 0.8rem;
  font-weight: 400;
  color: #64748b;
  margin-top: -0.25rem;
}

button {
  align-self: end;
  padding: 0.75rem 1.25rem;
  border-radius: 10px;
  background: linear-gradient(120deg, #2563eb, #38bdf8);
  border: none;
  color: #fff;
  font-weight: 600;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

button:disabled {
  opacity: 0.7;
  cursor: wait;
}

button:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 20px rgba(37, 99, 235, 0.2);
}

.error {
  color: #dc2626;
  background: #fee2e2;
  border-radius: 8px;
  padding: 0.75rem 1rem;
}

.placeholder {
  color: #64748b;
}
</style>
