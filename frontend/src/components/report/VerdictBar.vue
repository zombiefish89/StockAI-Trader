<template>
  <div class="rounded-2xl border border-slate-200/70 bg-white p-6 shadow-sm space-y-4">
    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div class="flex flex-wrap items-center gap-4">
        <el-tag :type="tagType" class="rounded-full px-4 py-1 text-sm font-semibold">
          {{ decisionLabel }}
        </el-tag>
        <span class="text-sm text-slate-500">
          置信度
          <span class="ml-1 text-base font-semibold text-slate-900">{{ confidenceText }}</span>
        </span>
        <span class="text-sm text-slate-500">标的：{{ report.ticker }} · 周期：{{ report.timeframe }}</span>
      </div>
      <span class="text-xs text-slate-400">
        更新时间：{{ asOfText }}
      </span>
    </div>
    <div class="space-y-2">
      <p class="text-base font-medium text-slate-900">{{ report.verdict.headline }}</p>
      <p class="text-sm leading-relaxed text-slate-600">
        {{ report.verdict.thesis }}
      </p>
    </div>
    <div class="flex flex-wrap gap-4 text-xs text-slate-500">
      <span v-if="report.metadata.dataSource">数据源：{{ report.metadata.dataSource }}</span>
      <span v-if="report.metadata.modelVersion">模型：{{ report.metadata.modelVersion }}</span>
      <span v-if="report.metadata.latencyMs !== null && report.metadata.latencyMs !== undefined">
        生成耗时：{{ report.metadata.latencyMs }} ms
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { StockAIReport, Verdict } from "../../types/report";

const props = defineProps<{
  report: StockAIReport;
}>();

const verdictLabels: Record<Verdict, string> = {
  HOLD: "观望",
  BUY: "积极做多",
  BUY_THE_DIP: "逢低布局",
  TRIM: "逢高减仓",
  SELL: "考虑卖出",
};

const verdictTags: Record<Verdict, string> = {
  HOLD: "info",
  BUY: "success",
  BUY_THE_DIP: "success",
  TRIM: "warning",
  SELL: "danger",
};

const decisionLabel = computed(() => verdictLabels[props.report.verdict.decision] ?? "观望");
const tagType = computed(() => verdictTags[props.report.verdict.decision] ?? "info");

const confidenceText = computed(() =>
  new Intl.NumberFormat("zh-CN", {
    style: "percent",
    minimumFractionDigits: 0,
  }).format(props.report.verdict.confidence)
);

const asOfText = computed(() =>
  new Intl.DateTimeFormat("zh-CN", {
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(props.report.asOf))
);
</script>
