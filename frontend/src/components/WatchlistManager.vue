<template>
  <section class="card">
    <header class="card__header">
      <h2>自选股批量分析</h2>
      <p class="muted">
        当前自选股共 {{ watchlist.length }} 只 · 更新时间：
        {{ updatedAt ? formatDate(updatedAt) : "尚未保存" }}
      </p>
    </header>

    <form class="inline-form" @submit.prevent="addSymbol">
      <input v-model="newSymbol" placeholder="输入股票代码并回车添加" />
      <button type="submit" :disabled="adding">
        {{ adding ? "添加中..." : "添加" }}
      </button>
      <button type="button" class="ghost" @click="refreshWatchlist" :disabled="loading">
        刷新
      </button>
    </form>

    <div v-if="watchlist.length" class="symbol-list">
      <button
        v-for="symbol in watchlist"
        :key="symbol"
        class="symbol-chip"
        @click="removeSymbol(symbol)"
      >
        {{ symbol }} ✕
      </button>
    </div>

    <div class="actions">
      <button type="button" @click="runAnalysis" :disabled="batchLoading || !watchlist.length">
        {{ batchLoading ? "分析中..." : "批量分析" }}
      </button>
    </div>

    <p v-if="message" class="status">{{ message }}</p>

    <section v-if="batchSummary" class="batch-summary">
      <h3>分析结果 · {{ batchSummary.timeframe }} · 更新时间 {{ formatDate(batchSummary.as_of) }}</h3>
      <p class="muted">
        总耗时 {{ (batchSummary.latency_ms / 1000).toFixed(2) }} 秒。
        <span v-if="batchFailed.length">失败：{{ batchFailed.join(", ") }}</span>
      </p>

      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>建议</th>
            <th>置信度</th>
            <th>入场 / 止损</th>
            <th>目标区间</th>
            <th>来源</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in batchRows" :key="item.ticker">
            <td>{{ item.ticker }}</td>
            <td>{{ item.action }}</td>
            <td>{{ formatPercent(item.confidence) }}</td>
            <td>{{ item.entry.toFixed(2) }} / {{ item.stop.toFixed(2) }}</td>
            <td>{{ item.targets.map((v) => v.toFixed(2)).join(" / ") }}</td>
            <td>{{ item.data_source ?? "N/A" }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import axios from "axios";

import type { AnalysisResultPayload } from "./AnalysisResult.vue";

interface WatchlistResponse {
  symbols: string[];
  updated_at: string;
}

interface BatchAnalysisResponse {
  as_of: string;
  timeframe: string;
  results: Record<string, AnalysisResultPayload>;
  failed: string[];
  latency_ms: number;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

const watchlist = ref<string[]>([]);
const updatedAt = ref<string>("");
const newSymbol = ref("");
const message = ref("");
const loading = ref(false);
const adding = ref(false);
const batchLoading = ref(false);
const batchData = ref<BatchAnalysisResponse | null>(null);
const batchFailed = ref<string[]>([]);

const batchSummary = computed(() => batchData.value);
const batchRows = computed(() => {
  if (!batchData.value) return [];
  return Object.values(batchData.value.results).map((item) => item);
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

async function refreshWatchlist() {
  loading.value = true;
  try {
    const { data } = await axios.get<WatchlistResponse>(`${API_BASE}/watchlist`);
    watchlist.value = data.symbols ?? [];
    updatedAt.value = data.updated_at ?? "";
  } catch (err) {
    message.value =
      err instanceof Error ? err.message : "获取自选股失败，请稍后重试。";
  } finally {
    loading.value = false;
  }
}

async function addSymbol() {
  const symbol = newSymbol.value.trim();
  if (!symbol) {
    return;
  }
  adding.value = true;
  try {
    const { data } = await axios.post<WatchlistResponse>(`${API_BASE}/watchlist/add`, {
      symbol,
    });
    watchlist.value = data.symbols ?? [];
    updatedAt.value = data.updated_at ?? "";
    newSymbol.value = "";
    message.value = "";
  } catch (err) {
    message.value =
      err instanceof Error ? err.message : "添加失败，请稍后重试。";
  } finally {
    adding.value = false;
  }
}

async function removeSymbol(symbol: string) {
  try {
    const { data } = await axios.post<WatchlistResponse>(`${API_BASE}/watchlist/remove`, {
      symbol,
    });
    watchlist.value = data.symbols ?? [];
    updatedAt.value = data.updated_at ?? "";
  } catch (err) {
    message.value =
      err instanceof Error ? err.message : "移除失败，请稍后重试。";
  }
}

async function runAnalysis() {
  batchLoading.value = true;
  message.value = "";
  try {
    const { data } = await axios.post<BatchAnalysisResponse>(
      `${API_BASE}/watchlist/analyze`,
      {}
    );
    batchData.value = data;
    batchFailed.value = data.failed ?? [];
  } catch (err) {
    message.value =
      err instanceof Error ? err.message : "批量分析失败，请稍后重试。";
  } finally {
    batchLoading.value = false;
  }
}

onMounted(() => {
  refreshWatchlist();
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

.card__header h2 {
  margin: 0;
}

.inline-form {
  display: flex;
  gap: 0.75rem;
}

.inline-form input {
  flex: 1;
  padding: 0.6rem 0.75rem;
  border: 1px solid #cbd5f5;
  border-radius: 8px;
}

.inline-form button {
  padding: 0.6rem 1rem;
  border-radius: 8px;
  border: none;
  background: linear-gradient(120deg, #2563eb, #38bdf8);
  color: #fff;
  font-weight: 600;
}

.inline-form button.ghost {
  background: transparent;
  color: #2563eb;
  border: 1px solid #2563eb;
}

.symbol-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.symbol-chip {
  background: #f1f5f9;
  border: none;
  border-radius: 999px;
  padding: 0.4rem 0.8rem;
  color: #0f172a;
  cursor: pointer;
}

.actions {
  display: flex;
  justify-content: flex-end;
}

.actions button {
  padding: 0.6rem 1rem;
  border-radius: 8px;
  border: none;
  background: linear-gradient(120deg, #22c55e, #16a34a);
  color: #fff;
  font-weight: 600;
}

.status {
  color: #dc2626;
}

.batch-summary table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 1rem;
}

.batch-summary th,
.batch-summary td {
  padding: 0.6rem;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
}

.muted {
  color: #64748b;
}
</style>
