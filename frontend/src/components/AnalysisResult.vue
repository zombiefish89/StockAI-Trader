<template>
  <el-card
    v-if="data"
    class="space-y-10 rounded-2xl border border-slate-200/70 shadow-sm"
    shadow="never"
  >
    <template #header>
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div class="space-y-1">
          <h2 class="text-xl font-semibold text-slate-900">{{ data.ticker }} 分析结果</h2>
          <el-text type="info" class="text-sm">
            更新时间：{{ formatDate(data.as_of) }} · 置信度 {{ toPercent(data.confidence) }}
          </el-text>
        </div>
        <el-tag
          :type="actionTagType"
          effect="dark"
          class="h-fit self-start rounded-full px-4 py-1 text-sm font-medium md:self-center"
        >
          {{ actionText }}
        </el-tag>
      </div>
    </template>

    <!-- 投资决策建议 -->
    <section class="space-y-4">
      <header class="flex flex-col gap-2">
        <h3 class="text-lg font-semibold text-slate-900">投资决策建议</h3>
        <p class="text-sm text-slate-500">
          聚焦核心入场、风控与风险要点，辅助你快速判断交易动作。
        </p>
      </header>
      <el-row :gutter="20">
        <el-col :md="14" :xs="24">
          <div class="rounded-2xl border border-slate-200/60 bg-slate-50/70 p-6">
            <div class="flex flex-wrap items-center gap-4">
              <el-tag :type="actionTagType" class="rounded-full px-4 py-1 text-sm font-medium">
                {{ actionText }}
              </el-tag>
              <div class="text-sm text-slate-500">
                置信度 <span class="text-base font-semibold text-slate-900">{{ toPercent(data.confidence) }}</span>
              </div>
              <div class="text-sm text-slate-500">
                数据源：{{ data.data_source ?? "未知" }}
              </div>
            </div>
            <el-descriptions :column="2" class="mt-4" border>
              <el-descriptions-item label="参考价">{{ formatPrice(data.reference_price) }}</el-descriptions-item>
              <el-descriptions-item label="入场">{{ formatPrice(data.entry) }}</el-descriptions-item>
              <el-descriptions-item label="止损">{{ formatPrice(data.stop) }}</el-descriptions-item>
              <el-descriptions-item label="ATR">{{ formatNumber(data.atr) }}</el-descriptions-item>
              <el-descriptions-item label="目标区间" :span="2">
                {{ targetsText }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-col>
        <el-col :md="10" :xs="24">
          <div class="rounded-2xl border border-amber-200/80 bg-amber-50/70 p-6">
            <h4 class="text-sm font-semibold text-amber-700">风险提示</h4>
            <el-empty v-if="!data.risk_notes.length" description="暂无明显风险" />
            <ul v-else class="mt-3 space-y-2 text-sm text-amber-800">
              <li v-for="risk in data.risk_notes" :key="risk" class="flex gap-2">
                <span>•</span>
                <span>{{ risk }}</span>
              </li>
            </ul>
          </div>
        </el-col>
      </el-row>
    </section>

    <!-- 分析过程 -->
    <section class="space-y-4">
      <header class="flex flex-col gap-2">
        <h3 class="text-lg font-semibold text-slate-900">分析过程</h3>
        <p class="text-sm text-slate-500">
          汇总模型工序、量化指标与 AI 解释，帮助理解信号生成的依据。
        </p>
      </header>

      <el-row :gutter="20">
        <el-col :md="12" :xs="24">
          <div class="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-inner">
            <header class="mb-3 flex items-center justify-between">
              <h4 class="text-sm font-semibold text-slate-700">快速综述</h4>
              <el-tag size="small" type="info" class="rounded-full">AI 快速模式</el-tag>
            </header>
            <MarkdownRenderer :content="fastSummaryMarkdown" />
          </div>
        </el-col>
        <el-col :md="12" :xs="24">
          <div class="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-inner space-y-4">
            <header class="flex items-center justify-between">
              <h4 class="text-sm font-semibold text-slate-700">深度研判</h4>
              <el-tag size="small" type="warning" class="rounded-full">AI 深度模式</el-tag>
            </header>
            <MarkdownRenderer :content="deepContent.markdown" />
            <div v-if="deepContent.summary" class="rounded-xl border border-indigo-100 bg-indigo-50/80 p-4 text-sm">
              <h5 class="mb-2 font-semibold text-indigo-700">结构化结论</h5>
              <p v-if="deepContent.summary.conclusion" class="text-slate-800">
                结论：{{ deepContent.summary.conclusion }}
              </p>
              <ul v-if="deepContent.summary.evidence?.length" class="mt-2 space-y-1 text-slate-600">
                <li v-for="item in deepContent.summary.evidence" :key="item" class="flex gap-2">
                  <span>•</span>
                  <span>{{ item }}</span>
                </li>
              </ul>
            </div>
            <div v-if="deepContent.signalEntries.length" class="rounded-xl border border-slate-200/70 bg-slate-50/70 p-4">
              <h5 class="mb-3 text-sm font-semibold text-slate-700">关键量化信号</h5>
              <el-table
                :data="deepContent.signalEntries"
                size="small"
                stripe
                :show-header="false"
                class="rounded-lg"
              >
                <el-table-column prop="label" min-width="140" />
                <el-table-column prop="value" />
              </el-table>
            </div>
          </div>
        </el-col>
      </el-row>

      <div class="rounded-2xl border border-slate-200/60 bg-white p-5">
        <header class="mb-3 flex items-center justify-between">
          <h4 class="text-sm font-semibold text-slate-700">系统评分</h4>
          <el-tag size="small" type="success" class="rounded-full">量化模型</el-tag>
        </header>
        <el-empty v-if="!scoreEntries.length" description="暂无评分数据" />
        <el-table v-else :data="scoreEntries" size="small" stripe class="rounded-lg">
          <el-table-column prop="key" label="指标" min-width="160" />
          <el-table-column prop="value" label="得分" min-width="120" />
        </el-table>
      </div>
    </section>

    <!-- 决策理由 -->
    <section class="space-y-4">
      <header class="flex flex-col gap-2">
        <h3 class="text-lg font-semibold text-slate-900">决策理由</h3>
        <p class="text-sm text-slate-500">
          展示生成策略的因果链条，便于复盘与人工校验。
        </p>
      </header>
      <div class="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-inner">
        <el-empty v-if="!data.rationale.length" description="暂无决策说明" />
        <el-timeline v-else>
          <el-timeline-item
            v-for="item in data.rationale"
            :key="item"
            type="primary"
          >
            <span class="text-sm leading-relaxed text-slate-700">{{ item }}</span>
          </el-timeline-item>
        </el-timeline>
      </div>

      <div class="rounded-2xl border border-slate-200/60 bg-slate-900/95 p-5 text-slate-100">
        <header class="mb-3 flex items-center justify-between">
          <h4 class="text-sm font-semibold text-slate-100">执行框架</h4>
          <el-tag size="small" type="info" effect="dark" class="rounded-full bg-slate-800/80">AI 生成</el-tag>
        </header>
        <MarkdownRenderer :content="data.report" />
      </div>
    </section>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from "vue";
import MarkdownRenderer from "./MarkdownRenderer.vue";

export interface AnalysisResultPayload {
  ticker: string;
  as_of: string;
  action: string;
  entry: number;
  stop: number;
  targets: number[];
  confidence: number;
  rationale: string[];
  risk_notes: string[];
  report: string;
  latency_ms: number;
  reference_price: number;
  atr: number;
  quote_snapshot?: Record<string, unknown> | null;
  data_source?: string | null;
  scores: Record<string, number>;
  signals: Record<string, unknown>;
  ai_fast_summary?: string | null;
  ai_deep_summary?: string | null;
  ai_short_term_summary?: string | null; // legacy
  ai_long_term_summary?: string | null; // legacy
}

const props = defineProps<{
  data: AnalysisResultPayload;
}>();

const actionText = computed(() => {
  switch (props.data.action) {
    case "buy":
      return "建议逢低做多";
    case "sell":
      return "建议逢高减仓";
    default:
      return "信号中性，暂以观望为主";
  }
});

const actionTagType = computed(() => {
  switch (props.data.action) {
    case "buy":
      return "success";
    case "sell":
      return "danger";
    default:
      return "info";
  }
});

const scoreEntries = computed(() => {
  const entries = Object.entries(props.data.scores ?? {});
  return entries.map(([key, value]) => ({
    key,
    value: toPercent(value),
  }));
});

const targetsText = computed(() =>
  props.data.targets.map((v) => formatPrice(v)).join(" / ")
);

const formatDate = (iso: string) =>
  new Intl.DateTimeFormat("zh-CN", {
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));

function toPercent(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "percent",
    minimumFractionDigits: 0,
  }).format(value);
}

function formatPrice(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return value.toFixed(2);
}

function formatNumber(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return value.toFixed(2);
}

const fastSummary = computed(
  () => props.data.ai_fast_summary ?? props.data.ai_short_term_summary ?? null
);
const deepSummary = computed(
  () => props.data.ai_deep_summary ?? props.data.ai_long_term_summary ?? null
);

const fastSummaryMarkdown = computed(() => fastSummary.value?.trim() ?? "");

interface DeepContent {
  markdown: string;
  summary: { conclusion?: string; evidence?: string[] } | null;
  signalEntries: { label: string; value: string }[];
}

const deepContent = computed<DeepContent>(() => {
  const raw = deepSummary.value ?? "";
  const { markdown, json } = extractDeepSummary(raw);
  const summary =
    json && typeof json.summary === "object"
      ? {
          conclusion: typeof json.summary.conclusion === "string" ? json.summary.conclusion : undefined,
          evidence: Array.isArray(json.summary.evidence)
            ? json.summary.evidence.map((item: unknown) => String(item))
            : undefined,
        }
      : null;

  const signalEntries: { label: string; value: string }[] = [];
  if (json && json.signals && typeof json.signals === "object") {
    for (const [key, value] of Object.entries(json.signals)) {
      signalEntries.push({
        label: key,
        value: typeof value === "string" ? value : JSON.stringify(value),
      });
    }
  }

  return {
    markdown,
    summary,
    signalEntries,
  };
});

function extractDeepSummary(content?: string | null): { markdown: string; json: Record<string, any> | null } {
  if (!content) return { markdown: "", json: null };
  let markdown = content.trim();
  let json: Record<string, any> | null = null;

  // Prefer fenced code block with json language
  const codeBlockMatch = markdown.match(/```json([\s\S]*?)```/i);
  if (codeBlockMatch) {
    const candidate = codeBlockMatch[1].trim();
    try {
      json = JSON.parse(candidate);
      markdown = markdown.replace(codeBlockMatch[0], "").trim();
      return { markdown, json };
    } catch (err) {
      // fall through
    }
  }

  // Otherwise attempt to parse trailing JSON object
  const lastBrace = markdown.lastIndexOf("{");
  if (lastBrace !== -1) {
    const candidate = markdown.slice(lastBrace);
    try {
      json = JSON.parse(candidate);
      markdown = markdown.slice(0, lastBrace).trim();
    } catch (err) {
      json = null;
    }
  }

  return { markdown, json };
}
</script>
