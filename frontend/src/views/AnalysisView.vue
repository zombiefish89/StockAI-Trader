<template>
  <section class="flex flex-col gap-6">
    <el-card class="rounded-2xl border border-slate-200/60 shadow-sm" shadow="never">
      <template #header>
        <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div class="space-y-1">
            <h2 class="text-xl font-semibold text-slate-900">智能行情分析</h2>
            <el-text type="info">输入股票代码，选择周期，快速获取结构化的 AI 建议。</el-text>
          </div>
          <el-button
            type="primary"
            :loading="loading"
            @click="analyze"
          >
            {{ loading ? "分析中..." : "生成分析" }}
          </el-button>
        </div>
      </template>
      <el-form
        :model="form"
        label-position="top"
        size="large"
        @submit.prevent="analyze"
      >
        <el-row :gutter="20">
          <el-col :md="8" :sm="12" :xs="24" class="flex flex-col gap-2">
            <el-form-item label="股票代码">
              <el-input
                v-model="form.ticker"
                placeholder="例如 AAPL 或 600519.SS"
                clearable
              />
            </el-form-item>
          </el-col>
          <el-col :md="8" :sm="12" :xs="24" class="flex flex-col gap-2">
            <el-form-item label="时间粒度">
              <el-select v-model="form.timeframe" placeholder="选择周期">
                <el-option
                  v-for="option in timeframeOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <p class="mt-2 text-sm text-slate-500">
                周期越短信号越敏感噪音越高；如不确定建议保持日线。
              </p>
            </el-form-item>
          </el-col>
          <el-col :md="8" :sm="24" :xs="24" class="flex flex-col gap-2">
            <el-form-item label="AI 模式">
              <el-radio-group v-model="form.mode" size="large">
                <el-radio-button label="fast">快速分析</el-radio-button>
                <el-radio-button label="deep">深度分析</el-radio-button>
              </el-radio-group>
              <p class="mt-2 text-sm text-slate-500">
                快速模式追求响应速度；深度模式提供更全面的研判。
              </p>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      show-icon
      class="rounded-xl"
    >
      {{ error }}
    </el-alert>

    <el-empty
      v-else-if="!loading && !result"
      class="rounded-2xl bg-white py-10"
      description="输入股票后点击生成分析即可查看 AI 建议"
    />

    <AnalysisResult v-if="result" :data="result" />
  </section>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import axios from "axios";
import AnalysisResult, {
  type AnalysisResultPayload,
} from "../components/AnalysisResult.vue";

interface AnalysisForm {
  ticker: string;
  timeframe: string;
  mode: "fast" | "deep";
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

const timeframeOptions = [
  { value: "1d", label: "日线 · 中短线判断" },
  { value: "1h", label: "小时线 · 日内趋势" },
  { value: "15m", label: "15 分钟 · 短线节奏" },
  { value: "5m", label: "5 分钟 · 超短/高频观察" },
];

const form = reactive<AnalysisForm>({
  ticker: "AAPL",
  timeframe: "1d",
  mode: "fast",
});

const loading = ref(false);
const error = ref("");
const result = ref<AnalysisResultPayload | null>(null);

async function analyze() {
  if (!form.ticker.trim()) {
    error.value = "请填写需要分析的股票代码。";
    return;
  }

  error.value = "";
  loading.value = true;
  try {
    const { data } = await axios.post<AnalysisResultPayload>(
      `${API_BASE}/analyze`,
      {
        ticker: form.ticker.trim(),
        timeframe: form.timeframe,
        ai_modes: [form.mode],
      }
    );
    result.value = data;
  } catch (err) {
    error.value =
      err instanceof Error
        ? err.message
        : "分析失败，请稍后重试或检查后端服务。";
  } finally {
    loading.value = false;
  }
}
</script>
