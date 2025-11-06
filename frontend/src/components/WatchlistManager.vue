<template>
  <el-card class="flex flex-col gap-6 rounded-2xl border border-slate-200/70 shadow-sm" shadow="never">
    <template #header>
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div class="space-y-1">
          <h2 class="text-xl font-semibold text-slate-900">自选股批量分析</h2>
          <el-text type="info" class="text-sm">
            当前自选股 {{ watchlist.length }} 只 · 更新时间：
            {{ updatedAt ? formatDate(updatedAt) : "尚未保存" }}
          </el-text>
        </div>
        <el-button
          type="info"
          plain
          :loading="loading"
          class="self-start md:self-auto"
          @click="refreshWatchlist"
        >
          刷新
        </el-button>
      </div>
    </template>

    <el-form class="max-w-lg" @submit.prevent="addSymbol">
      <el-form-item label="添加股票">
        <el-input
          v-model="newSymbol"
          placeholder="输入股票代码并回车添加"
          clearable
          @keyup.enter="addSymbol"
        >
          <template #append>
            <el-button type="primary" :loading="adding" @click="addSymbol" class="whitespace-nowrap">
              添加
            </el-button>
          </template>
        </el-input>
      </el-form-item>
    </el-form>

    <el-space
      v-if="watchlist.length"
      wrap
      :size="8"
      class="px-2"
    >
      <el-tag
        v-for="symbol in watchlist"
        :key="symbol"
        type="primary"
        effect="plain"
        closable
        class="rounded-full px-3 py-1"
        @close="removeSymbol(symbol)"
      >
        {{ symbol }}
      </el-tag>
    </el-space>

    <el-divider class="my-0" />

    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div class="flex items-center">
        <el-switch
          v-model="useLLM"
          active-text="启用 AI 总结"
          inactive-text="关闭 AI 总结"
        />
      </div>
      <el-button
        type="success"
        :loading="batchLoading"
        :disabled="!watchlist.length"
        class="w-full md:w-auto"
        @click="runAnalysis"
      >
        {{ batchLoading ? "分析中..." : "批量分析" }}
      </el-button>
    </div>

    <el-alert
      v-if="message"
      class="rounded-xl"
      type="error"
      :title="message"
      :closable="false"
      show-icon
    />

    <section
      v-if="batchSummary"
      class="rounded-2xl border border-slate-200/60 bg-slate-50/60 px-6 py-5 shadow-inner"
    >
      <header class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div class="space-y-1">
          <h3 class="text-lg font-semibold text-slate-900">
            批量分析 · {{ batchSummary.timeframe }} · 更新时间
            {{ formatDate(batchSummary.as_of) }}
          </h3>
          <el-text type="info" class="text-sm">
            总耗时 {{ (batchSummary.latency_ms / 1000).toFixed(2) }} 秒
          </el-text>
        </div>
        <el-tag v-if="batchFailed.length" type="danger" class="rounded-full">
          失败：{{ batchFailed.join(", ") }}
        </el-tag>
      </header>
      <el-alert
        v-if="batchSummary.ai_summary"
        type="success"
        :closable="false"
        show-icon
        class="mt-4 rounded-xl"
        :title="`AI 总结：${batchSummary.ai_summary}`"
      />

      <el-table
        :data="batchRows"
        stripe
        border
        size="small"
        v-if="batchRows.length"
        class="mt-4 rounded-xl"
      >
        <el-table-column prop="ticker" label="股票" min-width="100" />
        <el-table-column prop="action" label="建议" min-width="100" />
        <el-table-column label="置信度" min-width="100">
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
        <el-table-column prop="data_source" label="来源" min-width="120">
          <template #default="{ row }">
            {{ row.data_source ?? "N/A" }}
          </template>
        </el-table-column>
      </el-table>
      <el-empty
        v-else
        description="暂无分析结果"
        class="mt-4 rounded-xl bg-white py-6"
      />
    </section>
  </el-card>
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
  macro?: Record<string, unknown>;
  opportunities?: Record<string, unknown>;
  ai_summary?: string | null;
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
const useLLM = ref(false);

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
      {
        use_llm: useLLM.value,
      }
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
