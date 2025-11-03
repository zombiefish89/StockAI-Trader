<template>
  <section class="card">
    <header class="card__header">
      <h2>宏观板块概览</h2>
      <button type="button" @click="refresh" :disabled="loading">
        {{ loading ? "刷新中..." : "刷新" }}
      </button>
    </header>
    <p class="muted">更新时间：{{ generatedAt ? formatDate(generatedAt) : "暂无" }}</p>
    <p v-if="error" class="status">{{ error }}</p>

    <div v-if="overview" class="overview">
      <h3>市场摘要</h3>
      <p>{{ overview }}</p>
    </div>

    <div class="grid">
      <section v-if="highlights.length">
        <h3>重点亮点</h3>
        <ul>
          <li v-for="item in highlights" :key="item">
            {{ item }}
          </li>
        </ul>
      </section>
      <section v-if="risks.length">
        <h3>潜在风险</h3>
        <ul>
          <li v-for="item in risks" :key="item">
            {{ item }}
          </li>
        </ul>
      </section>
    </div>

    <section v-if="indicesRows.length">
      <h3>主要指数</h3>
      <table>
        <thead>
          <tr>
            <th>指数</th>
            <th>收盘</th>
            <th>涨跌幅</th>
            <th>成交量(亿)</th>
            <th>量能变化</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in indicesRows" :key="item.name">
            <td>{{ item.name }}</td>
            <td>{{ item.close?.toFixed(2) ?? "-" }}</td>
            <td :class="item.change_pct >= 0 ? 'up' : 'down'">
              {{ formatPercent(item.change_pct / 100) }}
            </td>
            <td>{{ item.volume ? (item.volume / 1e8).toFixed(1) : "-" }}</td>
            <td>{{ item.volume_change_pct ? formatPercent(item.volume_change_pct / 100) : "-" }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <div class="grid">
      <section v-if="topSectors.length">
        <h3>领涨板块</h3>
        <ul>
          <li v-for="item in topSectors" :key="item.name">
            {{ item.name }} · {{ formatPercent(item.change_pct / 100) }}
            <span v-if="item.fund_flow"> · 主力 {{ (item.fund_flow / 1e8).toFixed(2) }} 亿</span>
            <span v-if="item.leaders?.length">
              · 龙头：
              {{
                item.leaders
                  .slice(0, 2)
                  .map((lead) =>
                    `${lead.name ?? lead.code}(${formatPercent((lead.change_pct ?? 0) / 100)})`
                  )
                  .join("、")
              }}
            </span>
          </li>
        </ul>
      </section>
      <section v-if="weakSectors.length">
        <h3>领跌板块</h3>
        <ul>
          <li v-for="item in weakSectors" :key="item.name">
            {{ item.name }} · {{ formatPercent(item.change_pct / 100) }}
            <span v-if="item.fund_flow"> · 主力 {{ (item.fund_flow / 1e8).toFixed(2) }} 亿</span>
            <span v-if="item.leaders?.length">
              · 龙头：
              {{
                item.leaders
                  .slice(0, 2)
                  .map((lead) =>
                    `${lead.name ?? lead.code}(${formatPercent((lead.change_pct ?? 0) / 100)})`
                  )
                  .join("、")
              }}
            </span>
          </li>
        </ul>
      </section>
    </div>

    <section v-if="breadth">
      <h3>市场宽度</h3>
      <p>
        涨：{{ breadth.advance ?? "-" }} · 跌：{{ breadth.decline ?? "-" }}
        · 涨停：{{ breadth.limit_up ?? "-" }} · 跌停：{{ breadth.limit_down ?? "-" }}
      </p>
    </section>
    <section v-if="Object.keys(sentiment).length">
      <h3>情绪指标</h3>
      <p v-if="sentiment.northbound_net !== undefined">
        北向资金：
        <span :class="(sentiment.northbound_net ?? 0) >= 0 ? 'up' : 'down'">
          {{ ((sentiment.northbound_net ?? 0) / 1e8).toFixed(2) }} 亿
        </span>
      </p>
      <p v-if="sentiment.advance_decline_ratio !== undefined">
        涨跌比：{{ sentiment.advance_decline_ratio?.toFixed(2) }}
      </p>
    </section>
    <section v-if="lhbList.length">
      <h3>龙虎榜焦点</h3>
      <ul>
        <li v-for="item in lhbList" :key="item.code ?? item.name">
          <strong>{{ item.name ?? item.code }}</strong>
          <span v-if="item.net_buy !== undefined && item.net_buy !== null">
            · 净{{ (item.net_buy ?? 0) >= 0 ? "买" : "卖" }}
            <span :class="classifyMoney(item.net_buy)">{{ formatBillion(item.net_buy) }}</span>
          </span>
          <span v-if="item.change_pct !== undefined && item.change_pct !== null">
            · 当日涨跌 {{ formatPercent((item.change_pct ?? 0) / 100) }}
          </span>
          <span v-if="item.times">
            · 上榜 {{ item.times }} 次
          </span>
        </li>
      </ul>
    </section>
    <section v-if="newsList.length">
      <h3>市场新闻</h3>
      <ul class="news">
        <li v-for="item in newsList" :key="item.title">
          <div class="news__header">
            <a v-if="item.url" :href="item.url" target="_blank" rel="noopener">
              {{ item.title }}
            </a>
            <span v-else>{{ item.title }}</span>
          </div>
          <p class="news__meta">
            <span v-if="item.source">{{ item.source }}</span>
            <span v-if="item.time"> · {{ formatNewsTime(item.time) }}</span>
          </p>
          <p v-if="item.summary" class="news__summary">{{ item.summary }}</p>
        </li>
      </ul>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import axios from "axios";

interface SectorLeader {
  name?: string;
  code?: string;
  change_pct?: number;
}

interface LhbItem {
  code?: string;
  name?: string;
  net_buy?: number | null;
  buy_value?: number | null;
  sell_value?: number | null;
  times?: number | null;
  change_pct?: number | null;
  date?: string;
}

interface NewsItem {
  title: string;
  summary?: string | null;
  time?: string | null;
  source?: string | null;
  url?: string | null;
}

interface MacroSectorItem {
  name: string;
  change_pct: number;
  fund_flow?: number | null;
  leaders?: SectorLeader[];
}

interface MacroOverviewResponse {
  generated_at: string;
  overview: string;
  highlights: string[];
  risks: string[];
  indices: Record<string, Record<string, number>>;
  top_sectors: MacroSectorItem[];
  weak_sectors: MacroSectorItem[];
  breadth: Record<string, number | null>;
  sentiment: Record<string, number | null>;
  lhb: LhbItem[];
  news: NewsItem[];
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

const generatedAt = ref<string>("");
const overview = ref("");
const highlights = ref<string[]>([]);
const risks = ref<string[]>([]);
const indices = ref<MacroOverviewResponse["indices"]>({});
const topSectors = ref<MacroSectorItem[]>([]);
const weakSectors = ref<MacroSectorItem[]>([]);
const breadth = ref<Record<string, number | null>>({});
const sentiment = ref<Record<string, number | null>>({});
const lhbList = ref<LhbItem[]>([]);
const newsList = ref<NewsItem[]>([]);

const loading = ref(false);
const error = ref("");

const indicesRows = computed(() =>
  Object.entries(indices.value).map(([name, payload]) => ({
    name,
    ...payload,
  }))
);

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
    minimumFractionDigits: 2,
  }).format(value);
}

function formatBillion(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return `${(Math.abs(value) / 1e8).toFixed(2)} 亿`;
}

function classifyMoney(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "";
  }
  return value >= 0 ? "up" : "down";
}

function formatNewsTime(value?: string | null) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

async function refresh() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await axios.get<MacroOverviewResponse>(
      `${API_BASE}/macro/overview`
    );
    generatedAt.value = data.generated_at;
    overview.value = data.overview;
    highlights.value = data.highlights ?? [];
    risks.value = data.risks ?? [];
    indices.value = data.indices ?? {};
    topSectors.value = data.top_sectors ?? [];
    weakSectors.value = data.weak_sectors ?? [];
    breadth.value = data.breadth ?? {};
    sentiment.value = data.sentiment ?? {};
    lhbList.value = data.lhb ?? [];
    newsList.value = data.news ?? [];
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "宏观数据获取失败，请稍后重试。";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  refresh();
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

.grid {
  display: grid;
  gap: 1.5rem;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.overview {
  background: #f1f5f9;
  border-radius: 10px;
  padding: 1rem;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
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

.up {
  color: #16a34a;
}

.down {
  color: #dc2626;
}

.news {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.news__header a {
  color: #1d4ed8;
  text-decoration: none;
  font-weight: 600;
}

.news__header a:hover {
  text-decoration: underline;
}

.news__meta {
  color: #64748b;
  font-size: 0.85rem;
}

.news__summary {
  color: #475569;
  margin-top: 0.25rem;
}
</style>
