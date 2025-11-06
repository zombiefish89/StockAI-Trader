<template>
  <el-card class="rounded-2xl border border-slate-200/70 shadow-sm" shadow="never">
    <template #header>
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div class="space-y-1">
          <h2 class="text-xl font-semibold text-slate-900">宏观板块概览</h2>
          <el-text type="info">
            更新时间：{{ generatedAt ? formatDate(generatedAt) : "暂无" }}
          </el-text>
        </div>
        <el-button type="primary" :loading="loading" class="self-start md:self-auto" @click="refresh">
          {{ loading ? "刷新中..." : "刷新" }}
        </el-button>
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

    <el-row :gutter="20" class="mt-2">
      <el-col :md="12" :xs="24">
        <el-card
          shadow="never"
          class="rounded-xl border border-slate-200/70 shadow-none"
        >
          <template #header><strong class="text-sm text-slate-500">市场摘要</strong></template>
          <el-skeleton :loading="loading && !overview" animated :rows="3">
            <template #template>
              <el-skeleton-item variant="text" />
              <el-skeleton-item variant="text" />
              <el-skeleton-item variant="text" />
            </template>
            <p v-if="overview" class="leading-relaxed text-slate-700">{{ overview }}</p>
            <el-empty v-else description="暂无数据" />
          </el-skeleton>
        </el-card>
      </el-col>
      <el-col :md="12" :xs="24">
        <el-card
          shadow="never"
          class="rounded-xl border border-slate-200/70 shadow-none"
        >
          <template #header><strong class="text-sm text-slate-500">市场温度计</strong></template>
          <el-descriptions :column="1" border class="rounded-xl">
            <el-descriptions-item label="涨跌家数" v-if="hasBreadth" class="text-slate-700">
              <span>涨 {{ breadthData.advance ?? "-" }} · 跌 {{ breadthData.decline ?? "-" }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="涨停 / 跌停" v-if="hasBreadth" class="text-slate-700">
              <span>{{ breadthData.limit_up ?? "-" }} / {{ breadthData.limit_down ?? "-" }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="北向资金" v-if="sentimentData.northbound_net !== undefined">
              <el-tag
                :type="(sentimentData.northbound_net ?? 0) >= 0 ? 'success' : 'danger'"
                class="rounded-full"
              >
                {{ ((sentimentData.northbound_net ?? 0) / 1e8).toFixed(2) }} 亿
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="涨跌比" v-if="sentimentData.advance_decline_ratio !== undefined">
              {{ sentimentData.advance_decline_ratio?.toFixed(2) }}
            </el-descriptions-item>
            <el-descriptions-item label="情绪指标" v-if="!hasBreadth && !hasSentiment">
              暂无情绪数据
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="mt-4">
      <el-col :md="12" :xs="24">
        <el-card
          shadow="never"
          class="rounded-xl border border-slate-200/70 shadow-none"
        >
          <template #header><strong class="text-sm text-slate-500">重点亮点</strong></template>
          <el-empty v-if="!highlights.length" description="暂无亮点" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="item in highlights"
              :key="item"
              type="success"
            >
              {{ item }}
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
      <el-col :md="12" :xs="24">
        <el-card
          shadow="never"
          class="rounded-xl border border-slate-200/70 shadow-none"
        >
          <template #header><strong class="text-sm text-slate-500">潜在风险</strong></template>
          <el-empty v-if="!risks.length" description="暂无风险提示" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="item in risks"
              :key="item"
              type="warning"
            >
              {{ item }}
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
    </el-row>

    <el-card
      v-if="indicesRows.length"
      shadow="never"
      class="mt-4 rounded-xl border border-slate-200/70 shadow-none"
    >
      <template #header><strong class="text-sm text-slate-500">主要指数表现</strong></template>
      <el-table :data="indicesRows" size="small" border class="rounded-xl">
        <el-table-column prop="name" label="指数" min-width="140" />
        <el-table-column
          prop="close"
          label="收盘"
          :formatter="(_, __, value) => (value ? value.toFixed(2) : '-')"
          min-width="120"
        />
        <el-table-column prop="change_pct" label="涨跌幅" min-width="120">
          <template #default="{ row }">
            <el-tag :type="row.change_pct >= 0 ? 'success' : 'danger'">
              {{ formatPercent(row.change_pct / 100) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="成交量(亿)" min-width="120">
          <template #default="{ row }">
            {{ row.volume ? (row.volume / 1e8).toFixed(1) : "-" }}
          </template>
        </el-table-column>
        <el-table-column prop="volume_change_pct" label="量能变化" min-width="140">
          <template #default="{ row }">
            {{
              row.volume_change_pct
                ? formatPercent(row.volume_change_pct / 100)
                : "-"
            }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-row :gutter="20" class="mt-4">
      <el-col :md="12" :xs="24">
        <el-card
          v-if="topSectors.length"
          shadow="never"
          class="rounded-xl border border-slate-200/70 shadow-none"
        >
          <template #header><strong class="text-sm text-slate-500">领涨板块</strong></template>
          <el-table :data="topSectors" size="small" border class="rounded-xl">
            <el-table-column prop="name" label="板块" min-width="140" />
            <el-table-column label="涨跌幅" min-width="120">
              <template #default="{ row }">
                <el-tag type="success">{{ formatPercent(row.change_pct / 100) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="主力净流入" min-width="140">
              <template #default="{ row }">
                {{ row.fund_flow ? (row.fund_flow / 1e8).toFixed(2) + " 亿" : "-" }}
              </template>
            </el-table-column>
            <el-table-column label="龙头" min-width="200">
              <template #default="{ row }">
                {{
                  row.leaders && row.leaders.length
                    ? row.leaders
                        .slice(0, 2)
                        .map((lead) =>
                          `${lead.name ?? lead.code}(${formatPercent((lead.change_pct ?? 0) / 100)})`
                        )
                        .join("、")
                    : "-"
                }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :md="12" :xs="24">
        <el-card
          v-if="weakSectors.length"
          shadow="never"
          class="rounded-xl border border-slate-200/70 shadow-none"
        >
          <template #header><strong class="text-sm text-slate-500">领跌板块</strong></template>
          <el-table :data="weakSectors" size="small" border class="rounded-xl">
            <el-table-column prop="name" label="板块" min-width="140" />
            <el-table-column label="涨跌幅" min-width="120">
              <template #default="{ row }">
                <el-tag type="danger">{{ formatPercent(row.change_pct / 100) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="主力净流入" min-width="140">
              <template #default="{ row }">
                {{ row.fund_flow ? (row.fund_flow / 1e8).toFixed(2) + " 亿" : "-" }}
              </template>
            </el-table-column>
            <el-table-column label="龙头" min-width="200">
              <template #default="{ row }">
                {{
                  row.leaders && row.leaders.length
                    ? row.leaders
                        .slice(0, 2)
                        .map((lead) =>
                          `${lead.name ?? lead.code}(${formatPercent((lead.change_pct ?? 0) / 100)})`
                        )
                        .join("、")
                    : "-"
                }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="mt-4">
      <el-col :md="12" :xs="24">
        <el-card
          v-if="lhbList.length"
          shadow="never"
          class="rounded-xl border border-slate-200/70 shadow-none"
        >
          <template #header><strong class="text-sm text-slate-500">龙虎榜焦点</strong></template>
          <el-timeline>
            <el-timeline-item
              v-for="item in lhbList"
              :key="item.code ?? item.name"
              type="primary"
            >
              <div class="lhb-item">
                <strong>{{ item.name ?? item.code }}</strong>
                <span>
                  净{{ (item.net_buy ?? 0) >= 0 ? "买" : "卖" }}
                  <el-tag :type="(item.net_buy ?? 0) >= 0 ? 'success' : 'danger'" size="small" class="rounded-full">
                    {{ formatBillion(item.net_buy) }}
                  </el-tag>
                </span>
                <span v-if="item.change_pct !== undefined && item.change_pct !== null">
                  · 当日 {{ formatPercent((item.change_pct ?? 0) / 100) }}
                </span>
                <span v-if="item.times"> · 上榜 {{ item.times }} 次</span>
              </div>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
      <el-col :md="12" :xs="24">
        <el-card
          v-if="newsList.length"
          shadow="never"
          class="rounded-xl border border-slate-200/70 shadow-none"
        >
          <template #header><strong class="text-sm text-slate-500">市场新闻</strong></template>
          <el-scrollbar max-height="300" class="space-y-4">
            <div
              v-for="item in newsList"
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
  </el-card>
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

const breadthData = computed(() => breadth.value ?? {});
const sentimentData = computed(() => sentiment.value ?? {});
const hasBreadth = computed(
  () => Object.keys(breadthData.value).length > 0
);
const hasSentiment = computed(
  () => Object.keys(sentimentData.value).length > 0
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
