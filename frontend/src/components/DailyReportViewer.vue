<template>
  <el-card class="flex flex-col gap-6 rounded-2xl border border-slate-200/70 shadow-sm" shadow="never">
    <template #header>
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div class="space-y-1">
          <h2 class="text-xl font-semibold text-slate-900">每日自动报告</h2>
          <el-text v-if="currentReport" type="info" class="text-sm">
            生成时间：{{ formatDate(currentReport.generated_at) }} · 汇总至
            {{ formatDate(currentReport.as_of) }}
          </el-text>
          <el-text v-else type="info" class="text-sm">
            选择日期查看已生成报告
          </el-text>
        </div>
        <el-space wrap class="self-start md:self-auto">
          <el-select
            v-model="selectedDate"
            placeholder="选择日期"
            style="min-width: 160px"
            @change="loadReport"
          >
            <el-option
              v-for="item in summaries"
              :key="item.date"
              :label="item.date"
              :value="item.date"
            />
          </el-select>
          <el-button type="primary" :loading="loading" @click="refresh">
            {{ loading ? "刷新中..." : "刷新" }}
          </el-button>
        </el-space>
      </div>
    </template>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      class="rounded-xl"
    />

    <el-skeleton v-if="loading && !currentReport" animated :rows="6" />

    <el-empty
      v-else-if="!currentReport"
      description="未找到可用的日报，请选择其他日期或刷新。"
    />

    <div v-else class="flex flex-col gap-6">
      <el-alert
        v-if="currentReport.ai_summary"
        :title="`AI 总结：${currentReport.ai_summary}`"
        type="success"
        :closable="false"
        show-icon
        class="rounded-xl"
      />

      <el-row :gutter="20">
        <el-col :md="12" :xs="24">
          <el-card
            shadow="never"
            class="rounded-xl border border-slate-200/70 shadow-none"
          >
            <template #header><strong class="text-sm text-slate-500">市场概览</strong></template>
            <p class="leading-relaxed text-slate-700">
              {{ currentReport.market_overview || "暂无数据" }}
            </p>
          </el-card>
        </el-col>
        <el-col :md="12" :xs="24">
          <el-card
            shadow="never"
            class="rounded-xl border border-slate-200/70 shadow-none"
          >
            <template #header><strong class="text-sm text-slate-500">重点关注</strong></template>
            <el-empty v-if="!currentReport.highlights.length" description="暂无亮点" />
            <el-timeline v-else>
              <el-timeline-item
                v-for="item in currentReport.highlights"
                :key="highlightKey(item)"
                type="primary"
              >
                <template v-if="typeof item === 'string'">{{ item }}</template>
                <template v-else>
                  <strong>{{ item.ticker }}</strong>：{{ item.summary }}
                </template>
              </el-timeline-item>
            </el-timeline>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="20">
        <el-col :md="12" :xs="24">
          <el-card
            shadow="never"
            class="rounded-xl border border-slate-200/70 shadow-none"
          >
            <template #header><strong class="text-sm text-slate-500">潜在风险</strong></template>
            <el-empty v-if="!currentReport.risks.length" description="暂无风险提示" />
            <el-timeline v-else>
              <el-timeline-item
                v-for="risk in currentReport.risks"
                :key="risk"
                type="warning"
              >
                {{ risk }}
              </el-timeline-item>
            </el-timeline>
          </el-card>
        </el-col>
        <el-col :md="12" :xs="24">
          <el-card
            shadow="never"
            class="rounded-xl border border-slate-200/70 shadow-none"
          >
            <template #header><strong class="text-sm text-slate-500">市场宽度 & 情绪</strong></template>
            <el-descriptions :column="1" border class="rounded-xl">
              <el-descriptions-item label="涨跌家数" class="text-slate-700">
                涨 {{ currentReport.macro?.breadth?.advance ?? "-" }} · 跌
                {{ currentReport.macro?.breadth?.decline ?? "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="涨停 / 跌停" class="text-slate-700">
                {{ currentReport.macro?.breadth?.limit_up ?? "-" }} /
                {{ currentReport.macro?.breadth?.limit_down ?? "-" }}
              </el-descriptions-item>
              <el-descriptions-item
                label="北向资金"
                v-if="currentReport.macro?.sentiment?.northbound_net !== undefined"
              >
                <el-tag
                  :type="(currentReport.macro?.sentiment?.northbound_net ?? 0) >= 0 ? 'success' : 'danger'"
                  class="rounded-full"
                >
                  {{
                    ((currentReport.macro?.sentiment?.northbound_net ?? 0) / 1e8).toFixed(2)
                  }}
                  亿
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item
                label="涨跌比"
                v-if="currentReport.macro?.sentiment?.advance_decline_ratio !== undefined"
              >
                {{
                  currentReport.macro?.sentiment?.advance_decline_ratio?.toFixed(2)
                }}
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="20">
        <el-col :md="12" :xs="24">
          <el-card
            v-if="macroLhb.length"
            shadow="never"
            class="rounded-xl border border-slate-200/70 shadow-none"
          >
            <template #header><strong class="text-sm text-slate-500">龙虎榜焦点</strong></template>
            <el-timeline>
              <el-timeline-item
                v-for="item in macroLhb"
                :key="item.code ?? item.name"
                type="primary"
              >
                <div class="flex flex-col gap-2 text-slate-700">
                  <strong>{{ item.name ?? item.code }}</strong>
                  <span>
                    净{{ (item.net_buy ?? 0) >= 0 ? "买" : "卖" }}
                    <el-tag
                      :type="classifyMoney(item.net_buy)"
                      size="small"
                      class="rounded-full"
                    >
                      {{ formatBillion(item.net_buy) }}
                    </el-tag>
                  </span>
                  <span
                    v-if="item.change_pct !== undefined && item.change_pct !== null"
                  >
                    · 涨跌 {{ formatPercent((item.change_pct ?? 0) / 100) }}
                  </span>
                  <span v-if="item.times"> · 上榜 {{ item.times }} 次</span>
                </div>
              </el-timeline-item>
            </el-timeline>
          </el-card>
        </el-col>
        <el-col :md="12" :xs="24">
          <el-card
            v-if="macroNews.length"
            shadow="never"
            class="rounded-xl border border-slate-200/70 shadow-none"
          >
            <template #header><strong class="text-sm text-slate-500">市场新闻</strong></template>
            <el-scrollbar max-height="280" class="space-y-4">
              <div
                v-for="item in macroNews"
                :key="item.title"
                class="border-b border-slate-100 pb-4 last:border-b-0"
              >
                <h4 class="text-base font-semibold text-slate-900">
                  <a
                    v-if="item.url"
                    :href="item.url"
                    target="_blank"
                    rel="noopener"
                    class="text-indigo-600 transition hover:text-indigo-700"
                  >
                    {{ item.title }}
                  </a>
                  <span v-else>{{ item.title }}</span>
                </h4>
                <p class="mt-1 text-sm text-slate-500">
                  <span v-if="item.source">{{ item.source }}</span>
                  <span v-if="item.time"> · {{ formatNewsTime(item.time) }}</span>
                </p>
                <p v-if="item.summary" class="mt-2 text-sm leading-relaxed text-slate-700">
                  {{ item.summary }}
                </p>
              </div>
            </el-scrollbar>
          </el-card>
        </el-col>
      </el-row>

      <el-card
        shadow="never"
        class="rounded-xl border border-slate-200/70 shadow-none"
      >
        <template #header><strong class="text-sm text-slate-500">个股详情</strong></template>
        <el-table :data="detailRows" stripe border size="small" class="rounded-xl">
          <el-table-column prop="ticker" label="股票" min-width="100" />
          <el-table-column prop="action" label="建议" min-width="100" />
          <el-table-column prop="confidence" label="置信度" min-width="100">
            <template #default="{ row }">
              {{ formatPercent(row.confidence) }}
            </template>
          </el-table-column>
          <el-table-column label="入场 / 止损" min-width="160">
            <template #default="{ row }">
              {{ row.entry.toFixed(2) }} / {{ row.stop.toFixed(2) }}
            </template>
          </el-table-column>
          <el-table-column label="目标区间" min-width="180">
            <template #default="{ row }">
              {{ row.targets.map((v) => v.toFixed(2)).join(" / ") }}
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card
        v-if="opportunityRows.length"
        shadow="never"
        class="rounded-xl border border-slate-200/70 shadow-none"
      >
        <template #header><strong class="text-sm text-slate-500">机会扫描</strong></template>
        <el-text type="info" class="text-sm">
          方向：{{ currentReport?.opportunities?.direction ?? "-" }} · 周期：
          {{ currentReport?.opportunities?.timeframe ?? "-" }}
        </el-text>
        <el-table :data="opportunityRows" stripe border size="small" class="mt-3 rounded-xl">
          <el-table-column prop="ticker" label="股票" min-width="100" />
          <el-table-column prop="action" label="方向" min-width="100" />
          <el-table-column prop="score" label="得分" min-width="100">
            <template #default="{ row }">
              {{ row.score?.toFixed(2) ?? "-" }}
            </template>
          </el-table-column>
          <el-table-column prop="confidence" label="置信度" min-width="120">
            <template #default="{ row }">
              {{ formatPercent(row.confidence ?? 0) }}
            </template>
          </el-table-column>
          <el-table-column label="理由" min-width="220">
            <template #default="{ row }">
              {{ row.rationale?.[0] ?? "信号触发" }}
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-alert
        v-if="currentReport.failed.length"
        type="warning"
        :title="`分析失败：${currentReport.failed.join(', ')}`"
        :closable="false"
        show-icon
        class="rounded-xl"
      />
    </div>
  </el-card>
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

interface SectorLeader {
  name?: string;
  code?: string;
  change_pct?: number;
}

interface LhbEntry {
  code?: string;
  name?: string;
  net_buy?: number | null;
  change_pct?: number | null;
  times?: number | null;
}

interface NewsEntry {
  title: string;
  summary?: string | null;
  time?: string | null;
  source?: string | null;
  url?: string | null;
}

interface MacroSection {
  overview: string;
  top_sectors?: {
    name: string;
    change_pct: number;
    fund_flow?: number;
    leaders?: SectorLeader[];
  }[];
  weak_sectors?: {
    name: string;
    change_pct: number;
    fund_flow?: number;
    leaders?: SectorLeader[];
  }[];
  breadth?: Record<string, number | null>;
  sentiment?: Record<string, number | null>;
  lhb?: LhbEntry[];
  news?: NewsEntry[];
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
  ai_summary?: string | null;
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

const loadingSummaries = ref(false);
const loadingReport = ref(false);
const error = ref("");

const loading = computed(() => loadingSummaries.value || loadingReport.value);

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

const macroLhb = computed(() => currentReport.value?.macro?.lhb ?? []);
const macroNews = computed(() => currentReport.value?.macro?.news ?? []);

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

function formatBillion(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return `${(Math.abs(value) / 1e8).toFixed(2)} 亿`;
}

function classifyMoney(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "info";
  }
  return value >= 0 ? "success" : "danger";
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

async function fetchSummaries() {
  loadingSummaries.value = true;
  error.value = "";
  try {
    const { data } = await axios.get<ReportSummary[]>(`${API_BASE}/reports`);
    summaries.value = data;
    if (!selectedDate.value && data.length) {
      selectedDate.value = data[0].date;
    }
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "获取报告摘要失败，请稍后重试。";
  } finally {
    loadingSummaries.value = false;
  }
}

async function loadReport() {
  if (!selectedDate.value) {
    currentReport.value = null;
    return;
  }

  loadingReport.value = true;
  error.value = "";
  try {
    const { data } = await axios.get<ReportDetail>(
      `${API_BASE}/reports/${selectedDate.value}`
    );
    currentReport.value = data;
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "加载报告失败，请稍后重试。";
  } finally {
    loadingReport.value = false;
  }
}

async function refresh() {
  await fetchSummaries();
  if (selectedDate.value) {
    await loadReport();
  }
}

onMounted(async () => {
  await refresh();
});
</script>
