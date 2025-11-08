<template>
  <el-card
    shadow="never"
    class="rounded-2xl border border-slate-200/70 bg-white"
  >
    <template #header>
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-semibold text-slate-900">情景推演</h3>
        <p class="text-sm text-slate-500">预先规划不同市场路径的应对策略</p>
      </div>
    </template>
    <el-table :data="formattedRows" border stripe size="small" class="rounded-xl">
      <el-table-column prop="name" label="情景" min-width="140" />
      <el-table-column prop="probability" label="概率" min-width="100" />
      <el-table-column prop="trigger" label="触发条件" min-width="160" />
      <el-table-column prop="target" label="目标/区间" min-width="160" />
      <el-table-column prop="action" label="应对动作" min-width="160" />
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { ScenarioRow } from "../../types/report";

const props = defineProps<{
  rows: ScenarioRow[];
}>();

interface ScenarioDisplay {
  name: string;
  probability: string;
  trigger: string;
  target: string;
  action: string;
}

const formattedRows = computed<ScenarioDisplay[]>(() =>
  props.rows.map((row) => ({
    name: row.name,
    probability: formatProbability(row.probability),
    trigger: row.trigger ?? "—",
    target: formatTarget(row.target),
    action: row.action ?? "—",
  }))
);

function formatProbability(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—";
  }
  const normalized = value <= 1 ? value : value / 100;
  return new Intl.NumberFormat("zh-CN", {
    style: "percent",
    minimumFractionDigits: 0,
  }).format(normalized);
}

function formatTarget(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}
</script>
