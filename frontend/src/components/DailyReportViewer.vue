<template>
  <section class="card">
    <header class="card__header">
      <h2>每日自动报告</h2>
      <div class="controls">
        <label>
          查看日期
          <select v-model="selectedDate" @change="loadReport">
            <option value="" disabled>选择日期</option>
            <option v-for="item in summaries" :key="item.date" :value="item.date">
              {{ item.date }}
            </option>
          </select>
        </label>
        <button type="button" @click="refresh" :disabled="loading">
          {{ loading ? "刷新中..." : "刷新" }}
        </button>
      </div>
      <p class="muted" v-if="currentReport">
        生成时间：{{ formatDate(currentReport.generated_at) }} · 汇总至
        {{ formatDate(currentReport.as_of) }}
      </p>
    </header>

    <p v-if="error" class="status">{{ error }}</p>

    <div v-if="currentReport" class="report-body">
      <section>
        <h3>市场概览</h3>
        <p>{{ currentReport.market_overview || "暂无数据" }}</p>
      </section>

      <section v-if="currentReport.highlights.length">
        <h3>重点关注</h3>
        <ul>
          <li v-for="item in currentReport.highlights" :key="highlightKey(item)">
            <strong v-if="typeof item !== 'string' && item.ticker">{{ item.ticker }}</strong>
            <template v-if="typeof item === 'string'">{{ item }}</template>
            <template v-else>：{{ item.summary }}</template>
          </li>
        </ul>
      </section>

      <section v-if="currentReport.risks.length">
        <h3>潜在风险</h3>
        <ul>
          <li v-for="risk in currentReport.risks" :key="risk">{{ risk }}</li>
        </ul>
      </section>

      <section v-if="currentReport.macro">
        <h3>宏观概览</h3>
        <p>{{ currentReport.macro.overview || "暂无宏观数据" }}</p>
        <div class="grid">
          <div>
            <h4>领涨板块</h4>
            <ul>
              <li
                v-for="item in currentReport.macro.top_sectors || []"
                :key="item.name"
              >
                {{ item.name }} · {{ formatPercent(item.change_pct / 100) }}
              </li>
            </ul>
          </div>
          <div>
            <h4>领跌板块</h4>
            <ul>
              <li
                v-for="item in currentReport.macro.weak_sectors || []"
                :key="item.name"
              >
                {{ item.name }} · {{ formatPercent(item.change_pct / 100) }}
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section>
        <h3>个股详情</h3>
        <table>
          <thead>
            <tr>
              <th>股票</th>
              <th>建议</th>
              <th>置信度</th>
              <th>入场/止损</th>
              <th>目标区间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in detailRows" :key="row.ticker">
              <td>{{ row.ticker }}</td>
              <td>{{ row.action }}</td>
              <td>{{ formatPercent(row.confidence) }}</td>
              <td>{{ row.entry.toFixed(2) }} / {{ row.stop.toFixed(2) }}</td>
              <td>{{ row.targets.map((v) => v.toFixed(2)).join(" / ") }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="failed" v-if="currentReport.failed.length">
        <h3>分析失败</h3>
        <p>{{ currentReport.failed.join(", ") }}</p>
      </section>

      <section v-if="opportunityRows.length">
        <h3>机会扫描</h3>
        <p class="muted">
          方向：{{ currentReport?.opportunities?.direction ?? "-" }} · 周期：
          {{ currentReport?.opportunities?.timeframe ?? "-" }}
        </p>
        <table>
          <thead>
            <tr>
              <th>股票</th>
              <th>方向</th>
              <th>得分</th>
              <th>置信度</th>
              <th>理由</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in opportunityRows" :key="item.ticker + item.action">
              <td>{{ item.ticker }}</td>
              <td>{{ item.action }}</td>
              <td>{{ item.score?.toFixed(2) ?? "-" }}</td>
              <td>{{ formatPercent(item.confidence ?? 0) }}</td>
              <td>{{ item.rationale?.[0] ?? "信号触发" }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import axios from "axios";

type HighlightItem =
  | string
  | {
      ticker: string;
      summary: string;
    };

interface MacroSection {
  overview: string;
  top_sectors?: { name: string; change_pct: number }[];
  weak_sectors?: { name: string; change_pct: number }[];
  breadth?: Record<string, number>;
}

interface OpportunitySection {
  direction?: string;
  timeframe?: string;
  candidates?: {
    ticker: string;
    action: string;
    score?: number;
    confidence?: number;
    rationale?: string[];
  }[];
}

interface ReportSummary {
  date: string;
  generated_at: string;
  as_of: string;
  timeframe: string;
  market_overview: string;
  highlights: HighlightItem[];
  risks: string[];
  failed: string[];
  latency_ms: number;
  macro?: MacroSection;
  opportunities?: OpportunitySection;
}

interface ReportDetail extends ReportSummary {
  results: Record<
    string,
    {
      action: string;
      confidence: number;
      entry: number;
      stop: number;
      targets: number[];
      rationale: string[];
      risk_notes: string[];
      report: string;
      reference_price: number;
      atr: number;
      data_source?: string;
    }
  >;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

const summaries = ref<ReportSummary[]>([]);
const currentReport = ref<ReportDetail | null>(null);
const selectedDate = ref<string>("");
const loading = ref(false);
const error = ref("");

const detailRows = computed(() => {
  if (!currentReport.value) return [];
  return Object.entries(currentReport.value.results).map(([ticker, payload]) => ({
    ticker,
    ...payload,
  }));
});

const opportunityRows = computed(() => {
  if (!currentReport.value?.opportunities?.candidates) return [];
  return currentReport.value.opportunities.candidates;
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

function highlightKey(item: HighlightItem) {
  return typeof item === "string" ? item : item.ticker;
}

async function fetchSummaries() {
  const { data } = await axios.get<ReportSummary[]>(`${API_BASE}/reports`);
  summaries.value = data;
  if (!selectedDate.value && data.length) {
    selectedDate.value = data[0].date;
  }
}

async function loadReport() {
  if (!selectedDate.value) {
    currentReport.value = null;
    return;
  }
  try {
    const { data } = await axios.get<ReportDetail>(
      `${API_BASE}/reports/${selectedDate.value}`
    );
    currentReport.value = data;
    error.value = "";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "报告加载失败";
  }
}

async function refresh() {
  loading.value = true;
  try {
    await fetchSummaries();
    await loadReport();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "刷新失败";
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  await refresh();
  if (!currentReport.value) {
    try {
      const { data } = await axios.get<ReportDetail>(`${API_BASE}/reports/latest`);
      currentReport.value = data;
      selectedDate.value = data.date;
    } catch (err) {
      error.value = err instanceof Error ? err.message : "暂未生成报告";
    }
  }
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

.controls {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.controls select {
  margin-left: 0.5rem;
  padding: 0.4rem 0.6rem;
  border-radius: 8px;
  border: 1px solid #cbd5f5;
}

.controls button {
  padding: 0.5rem 1rem;
  border-radius: 8px;
  border: none;
  background: linear-gradient(120deg, #6366f1, #8b5cf6);
  color: #fff;
  font-weight: 600;
}

.report-body table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 1rem;
}

.report-body th,
.report-body td {
  padding: 0.6rem;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
}

.muted {
  color: #64748b;
}

.status {
  color: #dc2626;
}

.failed {
  background: #fef2f2;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  color: #b91c1c;
}

.grid {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}
</style>
