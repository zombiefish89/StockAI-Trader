<template>
  <div class="rounded-2xl border border-slate-200/70 bg-white p-6 shadow-sm space-y-4">
    <header class="flex items-center justify-between">
      <div>
        <h3 class="text-lg font-semibold text-slate-900">交易计划</h3>
        <p class="text-sm text-slate-500">执行参数仅供参考，结合实际风控调整</p>
      </div>
      <el-tag v-if="plan.size" size="small" type="info" class="rounded-full">
        仓位建议：{{ plan.size }}
      </el-tag>
    </header>

    <el-descriptions :column="2" border class="rounded-xl">
      <el-descriptions-item label="入场价格">
        <span v-if="plan.entry !== null && plan.entry !== undefined">
          {{ plan.entry?.toFixed(2) }}
        </span>
        <span v-else class="text-slate-400">根据触发条件分批建仓</span>
      </el-descriptions-item>
      <el-descriptions-item label="触发条件" v-if="plan.trigger">
        {{ plan.trigger }}
      </el-descriptions-item>
      <el-descriptions-item v-else label="触发条件">
        <span class="text-slate-400">关注价格区间与信号</span>
      </el-descriptions-item>
      <el-descriptions-item label="入场区间" v-if="plan.entryRange">
        <span>
          {{ formatRange(plan.entryRange) }}
        </span>
      </el-descriptions-item>
      <el-descriptions-item label="止损">
        <span v-if="plan.stop !== null && plan.stop !== undefined">
          {{ plan.stop?.toFixed(2) }}
        </span>
        <span v-else class="text-slate-400">遵循个人风控纪律</span>
      </el-descriptions-item>
    </el-descriptions>

    <div class="flex flex-col gap-3">
      <div v-if="plan.targets && plan.targets.length" class="flex flex-wrap items-center gap-3">
        <span class="text-sm font-medium text-slate-700">目标价格：</span>
        <el-tag
          v-for="target in plan.targets"
          :key="target"
          type="success"
          effect="plain"
          class="rounded-full px-3 py-1 text-sm"
        >
          {{ target.toFixed(2) }}
        </el-tag>
      </div>

      <p v-if="plan.targetNote" class="text-sm text-slate-500">
        {{ plan.targetNote }}
      </p>
      <p v-if="plan.notes" class="text-sm text-slate-500">
        {{ plan.notes }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { TradingPlan } from "../../types/report";

const props = defineProps<{
  plan: TradingPlan;
}>();

function formatRange(range: TradingPlan["entryRange"]) {
  if (!range) return "";
  const { min, max, note } = range;
  const parts: string[] = [];
  if (typeof min === "number") {
    parts.push(min.toFixed(2));
  }
  if (typeof max === "number") {
    parts.push(max.toFixed(2));
  }
  let text = parts.join(" - ");
  if (note) {
    text = text ? `${text}（${note}）` : note;
  }
  return text || "关注区间波动";
}
</script>
