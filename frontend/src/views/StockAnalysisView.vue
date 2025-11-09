<template>
  <section class="flex flex-col gap-6">
    <el-card class="rounded-2xl border border-slate-200/70 bg-white shadow-sm" shadow="never">
      <template #header>
        <div class="flex flex-col gap-2">
          <h2 class="text-lg font-semibold text-slate-900">个股分析</h2>
          <p class="text-sm text-slate-500">
            输入股票代码与周期，生成结构化的 AI 决策报告。
          </p>
        </div>
      </template>
      <el-form
        class="grid gap-4 md:grid-cols-[200px_160px_auto]"
        label-position="top"
        @submit.prevent="handleSubmit"
      >
        <el-form-item label="股票代码 / 名称">
          <el-autocomplete
            v-model="symbolInput"
            placeholder="如 茅台、苹果 或 300014"
            clearable
            :fetch-suggestions="fetchSymbolSuggestions"
            :debounce="250"
            value-key="ticker"
            :trigger-on-focus="false"
            @select="handleSymbolSelect"
            @keyup.enter="handleSubmit"
          >
            <template #default="{ item }">
              <div class="flex w-full items-center justify-between gap-3">
                <div class="flex items-center gap-2">
                  <span class="font-semibold text-slate-900">{{ item.ticker }}</span>
                  <span
                    v-if="item.market"
                    class="rounded-full bg-slate-100 px-2 py-0.5 text-xs uppercase text-slate-600"
                  >
                    {{ item.market }}
                  </span>
                </div>
                <div class="truncate text-sm text-slate-600">
                  {{ item.displayName }}
                </div>
              </div>
            </template>
          </el-autocomplete>
        </el-form-item>
        <el-form-item label="时间周期">
          <el-select v-model="timeframe" placeholder="选择周期">
            <el-option label="日线" value="1d" />
            <el-option label="4小时" value="4h" />
            <el-option label="小时线" value="1h" />
            <el-option label="15 分钟" value="15m" />
          </el-select>
        </el-form-item>
        <div class="flex items-end">
          <el-button type="primary" :loading="loading" @click="handleSubmit">
            {{ loading ? "加载中..." : "生成报告" }}
          </el-button>
        </div>
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
import { useSymbolSearch, type SymbolSuggestion } from "../composables/useSymbolSearch";
import VerdictBar from "../components/report/VerdictBar.vue";
import PlanCard from "../components/report/PlanCard.vue";
import ScenarioTable from "../components/report/ScenarioTable.vue";
import RiskList from "../components/report/RiskList.vue";
import MarkdownRenderer from "../components/MarkdownRenderer.vue";

const route = useRoute();
const router = useRouter();
const { report, loading, error, load, loadFromCache } = useReport();
const { fetchSuggestions: fetchSymbolSuggestions } = useSymbolSearch({ limit: 15 });

const symbolInput = ref<string>(parseSymbol(route.query.symbol));
const timeframe = ref<string>(parseTimeframe(route.query.timeframe));

const restored = loadFromCache();
if (!symbolInput.value && restored?.symbol) {
  symbolInput.value = restored.symbol;
}
if (!route.query.timeframe && restored?.timeframe) {
  timeframe.value = restored.timeframe;
}

watch(
  () => [route.query.symbol, route.query.timeframe],
  ([symbolQuery, timeframeQuery]) => {
    const parsedSymbol = parseSymbol(symbolQuery);
    const parsedTimeframe = parseTimeframe(timeframeQuery);
    symbolInput.value = parsedSymbol;
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

function handleSymbolSelect(item: SymbolSuggestion) {
  symbolInput.value = item.ticker.toUpperCase();
}

function parseSymbol(value: unknown): string {
  return typeof value === "string" ? value.toUpperCase() : "";
}

function parseTimeframe(value: unknown): string {
  return typeof value === "string" ? value : "1d";
}
</script>
