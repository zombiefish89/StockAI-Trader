<template>
  <section class="card">
    <header class="card__header">
      <h2>机会扫描器</h2>
      <button type="button" @click="scan" :disabled="loading">
        {{ loading ? "扫描中..." : "扫描机会" }}
      </button>
    </header>

    <form class="form" @submit.prevent="scan">
      <label>
        时间周期
        <select v-model="form.timeframe">
          <option value="1d">日线</option>
          <option value="1h">小时线</option>
          <option value="15m">15 分钟</option>
        </select>
      </label>
      <label>
        方向
        <select v-model="form.direction">
          <option value="long">做多</option>
          <option value="short">做空</option>
          <option value="all">全部</option>
        </select>
      </label>
      <label>
        股票池 (可选，逗号分隔)
        <textarea
          v-model="form.symbols"
          placeholder="AAPL, MSFT, NVDA"
          rows="3"
        ></textarea>
      </label>
    </form>

    <p v-if="error" class="status">{{ error }}</p>

    <section v-if="candidates.length">
      <h3>
        候选列表 · {{ dataMeta.direction }} ·
        {{ formatDate(dataMeta.generated_at) }}
      </h3>
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>建议</th>
            <th>得分</th>
            <th>置信度</th>
            <th>理由</th>
            <th>来源</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in candidates" :key="item.ticker">
            <td>{{ item.ticker }}</td>
            <td>{{ item.action }}</td>
            <td>{{ item.score.toFixed(2) }}</td>
            <td>{{ formatPercent(item.confidence) }}</td>
            <td>{{ item.rationale[0] ?? "信号触发" }}</td>
            <td>{{ item.data_source ?? "-" }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <p v-else-if="!loading" class="muted">暂无符合条件的机会。</p>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import axios from "axios";

interface OpportunityCandidate {
  ticker: string;
  action: string;
  score: number;
  confidence: number;
  rationale: string[];
  risk_notes: string[];
  data_source?: string | null;
  reference_price?: number | null;
}

interface OpportunityResponse {
  generated_at: string;
  direction: string;
  timeframe: string;
  candidates: OpportunityCandidate[];
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

const form = reactive({
  timeframe: "1d",
  direction: "long",
  symbols: "",
});

const loading = ref(false);
const error = ref("");
const candidates = ref<OpportunityCandidate[]>([]);
const dataMeta = reactive({
  generated_at: "",
  direction: "",
});

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatPercent(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "percent",
    minimumFractionDigits: 0,
  }).format(value);
}

function parseSymbols(input: string) {
  if (!input.trim()) return undefined;
  return input
    .split(/[,，\s]+/)
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
}

async function scan() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await axios.post<OpportunityResponse>(
      `${API_BASE}/scanner/opportunities`,
      {
        timeframe: form.timeframe,
        direction: form.direction,
        tickers: parseSymbols(form.symbols),
      }
    );
    candidates.value = data.candidates ?? [];
    dataMeta.generated_at = data.generated_at;
    dataMeta.direction = data.direction;
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "机会扫描失败，请稍后重试。";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  scan();
});
</script>

<style scoped>
.card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 10px 25px rgba(15, 23, 42, 0.06);
  padding: 1.5rem;
  margin-top: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.form {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

select,
textarea {
  border: 1px solid #cbd5f5;
  border-radius: 8px;
  padding: 0.6rem 0.75rem;
  font-size: 0.95rem;
  width: 100%;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  padding: 0.6rem;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
}

.muted {
  color: #64748b;
}

.status {
  color: #dc2626;
}
</style>
