<template>
  <section class="flex flex-col gap-6">
    <el-card class="rounded-2xl border border-slate-200/70" shadow="never">
      <template #header>
        <div class="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">个股分析历史</h2>
            <p class="text-sm text-slate-500">按股票与周期检索历史的 AI 报告。</p>
          </div>
          <el-button type="primary" @click="handleRefresh" :loading="loading">刷新</el-button>
        </div>
      </template>

      <el-form class="grid gap-4 md:grid-cols-[200px_160px_auto]" label-position="top" @submit.prevent>
        <el-form-item label="股票代码">
          <el-input v-model.trim="filters.ticker" placeholder="如 600519.SH" clearable />
        </el-form-item>
        <el-form-item label="时间周期">
          <el-select v-model="filters.timeframe" placeholder="全部" clearable>
            <el-option label="日线" value="1d" />
            <el-option label="4小时" value="4h" />
            <el-option label="小时线" value="1h" />
            <el-option label="15 分钟" value="15m" />
          </el-select>
        </el-form-item>
        <div class="flex items-end gap-3">
          <el-button type="primary" @click="handleSearch" :loading="loading">查询</el-button>
          <el-button @click="handleReset" :disabled="loading">重置</el-button>
        </div>
      </el-form>

      <el-table :data="records" v-loading="loading" stripe border class="mt-4 rounded-xl" @row-click="handleRowClick">
        <el-table-column prop="ticker" label="股票" min-width="120" />
        <el-table-column prop="timeframe" label="周期" min-width="80" />
        <el-table-column label="结论" min-width="160">
          <template #default="{ row }">
            <div class="flex flex-col">
              <span class="font-medium">{{ row.report.verdict.decision }}</span>
              <span class="text-xs text-slate-500">置信度 {{ (row.report.verdict.confidence * 100).toFixed(1) }}%</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="report.verdict.headline" label="摘要" min-width="200">
          <template #default="{ row }">
            <span class="text-sm text-slate-700">{{ row.report.verdict.headline }}</span>
          </template>
        </el-table-column>
        <el-table-column label="分析时间" min-width="220">
          <template #default="{ row }">
            <div class="flex flex-col text-sm text-slate-600">
              <span>生成：{{ formatDate(row.createdAt) }}</span>
              <span>行情：{{ formatDate(row.asOf) }}</span>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !records.length" description="暂无历史记录" class="mt-6" />

      <div class="mt-4 flex items-center justify-end gap-4" v-if="records.length">
        <el-pagination
          background
          layout="prev, pager, next"
          :page-size="pagination.limit"
          :current-page="currentPage"
          :total="Math.max(pagination.offset + records.length + (records.length === pagination.limit ? pagination.limit : 0), pagination.offset + records.length)"
          @current-change="handlePageChange"
        />
      </div>
    </el-card>

    <el-drawer v-model="drawerVisible" size="50%" :title="drawerTitle" destroy-on-close>
      <template v-if="selectedRecord">
        <section class="space-y-6">
          <header class="space-y-1">
            <p class="text-sm text-slate-500">
              生成：{{ formatDate(selectedRecord.createdAt) }} · 行情：{{ formatDate(selectedRecord.asOf) }}
            </p>
          </header>

          <VerdictBar :report="selectedReport" />
          <PlanCard v-if="selectedReport?.plan" :plan="selectedReport.plan" />
          <ScenarioTable v-if="selectedReport?.scenarios?.length" :rows="selectedReport.scenarios" />
          <RiskList v-if="selectedReport?.riskNotes?.length" :items="selectedReport.riskNotes" />

          <article class="space-y-3">
            <h4 class="text-lg font-semibold text-slate-900">分析详情</h4>
            <MarkdownRenderer :content="selectedReport?.analysisNarrative ?? '-'" />
          </article>
        </section>
      </template>
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { fetchAnalysisHistory } from "../services/api";
import type { AnalysisHistoryRecord } from "../types/history";
import VerdictBar from "../components/report/VerdictBar.vue";
import PlanCard from "../components/report/PlanCard.vue";
import ScenarioTable from "../components/report/ScenarioTable.vue";
import RiskList from "../components/report/RiskList.vue";
import MarkdownRenderer from "../components/MarkdownRenderer.vue";

const loading = ref(false);
const records = ref<AnalysisHistoryRecord[]>([]);
const filters = reactive({
  ticker: "",
  timeframe: "",
});
const pagination = reactive({
  limit: 10,
  offset: 0,
});

const drawerVisible = ref(false);
const selectedRecord = ref<AnalysisHistoryRecord | null>(null);

const currentPage = computed(() => Math.floor(pagination.offset / pagination.limit) + 1);

const drawerTitle = computed(() => {
  if (!selectedRecord.value) return "";
  return `分析详情 · ${selectedRecord.value.ticker}`;
});

const selectedReport = computed(() => selectedRecord.value?.report ?? null);

function formatDate(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

async function loadHistory() {
  loading.value = true;
  try {
    records.value = await fetchAnalysisHistory({
      ticker: filters.ticker || undefined,
      timeframe: filters.timeframe || undefined,
      limit: pagination.limit,
      offset: pagination.offset,
    });
  } catch (err) {
    console.error("history fetch failed", err);
    records.value = [];
  } finally {
    loading.value = false;
  }
}

function handleSearch() {
  pagination.offset = 0;
  loadHistory();
}

function handleReset() {
  filters.ticker = "";
  filters.timeframe = "";
  pagination.offset = 0;
  loadHistory();
}

function handleRefresh() {
  loadHistory();
}

function handlePageChange(page: number) {
  pagination.offset = (page - 1) * pagination.limit;
  loadHistory();
}

function handleRowClick(row: AnalysisHistoryRecord) {
  selectedRecord.value = row;
  drawerVisible.value = true;
}

onMounted(() => {
  loadHistory();
});
</script>
