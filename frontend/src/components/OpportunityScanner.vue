<template>
  <el-card class="flex flex-col gap-6 rounded-2xl border border-slate-200/70 shadow-sm" shadow="never">
    <template #header>
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div class="space-y-1">
          <h2 class="text-xl font-semibold text-slate-900">机会扫描器</h2>
          <el-text type="info" class="text-sm">
            候选列表 · {{ dataMeta.direction || "全部方向" }} ·
            {{ dataMeta.generated_at ? formatDate(dataMeta.generated_at) : "敬请期待" }}
          </el-text>
        </div>
        <el-button type="primary" :loading="loading" class="self-start md:self-auto" @click="scan">
          {{ loading ? "扫描中..." : "重新扫描" }}
        </el-button>
      </div>
    </template>

    <el-form
      :model="form"
      class="rounded-xl bg-slate-100/60 px-4 py-4 md:px-6"
      label-position="top"
      @submit.prevent="scan"
    >
      <el-row :gutter="20">
        <el-col :md="6" :sm="12" :xs="24">
          <el-form-item label="时间周期">
            <el-select v-model="form.timeframe">
              <el-option label="日线" value="1d" />
              <el-option label="小时线" value="1h" />
              <el-option label="15 分钟" value="15m" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :md="6" :sm="12" :xs="24">
          <el-form-item label="方向">
            <el-select v-model="form.direction">
              <el-option label="做多" value="long" />
              <el-option label="做空" value="short" />
              <el-option label="全部" value="all" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :md="12" :xs="24">
          <el-form-item label="股票池 (可选，逗号或空格分隔)">
            <el-input
              v-model="form.symbols"
              type="textarea"
              :rows="3"
              placeholder="AAPL, MSFT, NVDA"
            />
          </el-form-item>
        </el-col>
      </el-row>
    </el-form>

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      :closable="false"
      class="rounded-xl"
    />

    <el-table
      v-if="candidates.length"
      :data="candidates"
      stripe
      border
      size="small"
      class="rounded-xl"
    >
      <el-table-column prop="ticker" label="股票" min-width="100" />
      <el-table-column prop="action" label="建议" min-width="100" />
      <el-table-column prop="score" label="得分" min-width="100">
        <template #default="{ row }">
          {{ row.score.toFixed(2) }}
        </template>
      </el-table-column>
      <el-table-column prop="confidence" label="置信度" min-width="120">
        <template #default="{ row }">
          {{ formatPercent(row.confidence) }}
        </template>
      </el-table-column>
      <el-table-column label="理由" min-width="220">
        <template #default="{ row }">
          {{ row.rationale[0] ?? "信号触发" }}
        </template>
      </el-table-column>
      <el-table-column prop="data_source" label="来源" min-width="120">
        <template #default="{ row }">
          {{ row.data_source ?? "-" }}
        </template>
      </el-table-column>
    </el-table>

    <el-empty
      v-else-if="!loading"
      description="暂无符合条件的机会"
      class="rounded-xl bg-white py-6"
    />
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import axios from "axios";
import { API_BASE } from "../config/api";

interface OpportunityCandidate {
  ticker: string;
  action: string;
  score: number;
  confidence: number;
  rationale: string[];
  risk_notes: string[];
  data_source?: string | null;
  reference_price?: number | null;
}

interface OpportunityResponse {
  generated_at: string;
  direction: string;
  timeframe: string;
  candidates: OpportunityCandidate[];
}


const form = reactive({
  timeframe: "1d",
  direction: "long",
  symbols: "",
});

const loading = ref(false);
const error = ref("");
const candidates = ref<OpportunityCandidate[]>([]);
const dataMeta = reactive({
  generated_at: "",
  direction: "",
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

function parseSymbols(input: string) {
  if (!input.trim()) return undefined;
  return input
    .split(/[,，\s]+/)
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
}

async function scan() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await axios.post<OpportunityResponse>(
      `${API_BASE}/scanner/opportunities`,
      {
        timeframe: form.timeframe,
        direction: form.direction,
        tickers: parseSymbols(form.symbols),
      }
    );
    candidates.value = data.candidates ?? [];
    dataMeta.generated_at = data.generated_at;
    dataMeta.direction = data.direction;
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "机会扫描失败，请稍后重试。";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  scan();
});
</script>
