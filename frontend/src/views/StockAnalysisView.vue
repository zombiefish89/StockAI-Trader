<template>
  <section class="flex flex-col gap-6">
    <el-card
      class="rounded-2xl border border-slate-200/70 bg-white shadow-sm"
      shadow="never"
    >
      <template #header>
        <div class="flex flex-col gap-2">
          <h2 class="text-lg font-semibold text-slate-900">个股分析</h2>
          <p class="text-sm text-slate-500">
            输入股票代码与周期，生成结构化的 AI 决策报告。
          </p>
        </div>
      </template>
      <el-form
        class="grid gap-4 md:grid-cols-[350px_250px_auto]"
        label-position="left"
        @submit.prevent="handleSubmit"
      >
        <el-form-item label="股票代码 / 名称">
          <el-select
            v-model="symbolInput"
            class="w-full"
            placeholder="输入关键字选择股票"
            filterable
            remote
            :remote-method="handleSymbolSearch"
            :loading="searchingSymbols"
            clearable
            :reserve-keyword="true"
          >
            <el-option
              v-for="item in symbolOptions"
              :key="item.ticker"
              :label="formatSymbolOption(item)"
              :value="item.ticker"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="时间周期">
          <el-select v-model="timeframe" placeholder="选择周期">
            <el-option label="日线" value="1d" />
            <el-option label="4小时" value="4h" />
            <el-option label="小时线" value="1h" />
            <el-option label="15 分钟" value="15m" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            class="w-full md:w-auto"
            :loading="loading"
            @click="handleSubmit"
          >
            {{ loading ? "加载中..." : "分析" }}
          </el-button></el-form-item
        >
      </el-form>
    </el-card>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      class="rounded-xl"
    />

    <el-skeleton v-if="loading && !report" rows="6" animated />

    <el-empty
      v-else-if="!loading && !report"
      description="输入股票代码并点击生成报告"
      class="rounded-2xl bg-white py-10"
    />

    <template v-else-if="report">
      <VerdictBar :report="report" />
      <PlanCard v-if="report.plan" :plan="report.plan" />

      <ScenarioTable v-if="report.scenarios.length" :rows="report.scenarios" />
      <RiskList v-if="report.riskNotes.length" :items="report.riskNotes" />

      <el-card
        shadow="never"
        class="rounded-2xl border border-slate-200/70 bg-white"
      >
        <template #header>
          <h3 class="text-lg font-semibold text-slate-900">分析详情</h3>
        </template>
        <MarkdownRenderer :content="report.analysisNarrative" />
      </el-card>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useReport } from "../composables/useReport";
import { searchSymbols } from "../services/api";
import type { SymbolSearchResult } from "../types/symbols";
import VerdictBar from "../components/report/VerdictBar.vue";
import PlanCard from "../components/report/PlanCard.vue";
import ScenarioTable from "../components/report/ScenarioTable.vue";
import RiskList from "../components/report/RiskList.vue";
import MarkdownRenderer from "../components/MarkdownRenderer.vue";

const route = useRoute();
const router = useRouter();
const { report, loading, error, load, loadFromCache } = useReport();

const symbolOptions = ref<SymbolSearchResult[]>([]);
const searchingSymbols = ref(false);

const symbolInput = ref<string>(parseSymbol(route.query.symbol));
const timeframe = ref<string>(parseTimeframe(route.query.timeframe));

const restored = loadFromCache();
if (!symbolInput.value && restored?.symbol) {
  symbolInput.value = restored.symbol;
}
if (!route.query.timeframe && restored?.timeframe) {
  timeframe.value = restored.timeframe;
}

ensureOptionForSymbol(symbolInput.value);

watch(
  () => [route.query.symbol, route.query.timeframe],
  ([symbolQuery, timeframeQuery]) => {
    const parsedSymbol = parseSymbol(symbolQuery);
    const parsedTimeframe = parseTimeframe(timeframeQuery);
    symbolInput.value = parsedSymbol;
    ensureOptionForSymbol(parsedSymbol);
    timeframe.value = parsedTimeframe;
    if (parsedSymbol) {
      load(parsedSymbol, parsedTimeframe);
    } else if (!report.value) {
      loadFromCache();
    }
  },
  { immediate: true }
);

function handleSubmit() {
  const symbol = symbolInput.value.trim();
  if (!symbol) {
    return;
  }
  router.replace({
    path: "/stock",
    query: {
      symbol: symbol.toUpperCase(),
      timeframe: timeframe.value,
    },
  });
}

function parseSymbol(value: unknown): string {
  return typeof value === "string" ? value.toUpperCase() : "";
}

function parseTimeframe(value: unknown): string {
  return typeof value === "string" ? value : "1d";
}

async function handleSymbolSearch(query: string) {
  const keyword = query.trim();
  if (!keyword) {
    symbolOptions.value = [];
    return;
  }
  searchingSymbols.value = true;
  try {
    const response = await searchSymbols(keyword, { limit: 20 });
    symbolOptions.value = response.items;
  } finally {
    searchingSymbols.value = false;
  }
}

function ensureOptionForSymbol(ticker: string) {
  if (!ticker) return;
  if (symbolOptions.value.some((item) => item.ticker === ticker)) {
    return;
  }
  symbolOptions.value.push({
    ticker,
    displayName: ticker,
    aliases: [],
    market: undefined,
    exchange: undefined,
    nameCn: undefined,
    nameEn: undefined,
    score: undefined,
  } as SymbolSearchResult);
}

function formatSymbolOption(item: SymbolSearchResult) {
  const label = item.displayName || item.nameCn || item.nameEn || item.ticker;
  return `${item.ticker} · ${label}`;
}
</script>
