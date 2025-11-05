<template>
  <section class="card">
    <header class="card__header">
      <h2>{{ data.ticker }} 分析结果</h2>
      <p class="muted">
        更新时间：{{ formatDate(data.as_of) }} · 置信度 {{ toPercent(data.confidence) }}
      </p>
    </header>

    <div class="grid">
      <div>
        <h3>操作建议</h3>
        <p class="headline">{{ actionText }}</p>
        <p>入场：{{ data.entry.toFixed(2) }}</p>
        <p>止损：{{ data.stop.toFixed(2) }}</p>
        <p>目标：{{ targetsText }}</p>
      </div>

      <div>
        <h3>风险提示</h3>
        <ul>
          <li v-for="risk in data.risk_notes" :key="risk">
            {{ risk }}
          </li>
        </ul>
      </div>
    </div>

    <section>
      <h3>策略概要</h3>
      <ul v-if="data.rationale.length">
        <li v-for="item in data.rationale" :key="item">
          {{ item }}
        </li>
      </ul>
      <pre v-if="data.report" class="report">{{ data.report }}</pre>
    </section>

    <section v-if="data.ai_short_term_summary">
      <h3>AI 短线总结</h3>
      <div class="ai-block" v-html="shortSummaryHtml"></div>
    </section>

    <section v-if="data.ai_long_term_summary">
      <h3>AI 中长期分析</h3>
      <div class="ai-block" v-html="longSummaryHtml"></div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";

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
  ai_short_term_summary?: string | null;
  ai_long_term_summary?: string | null;
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

const targetsText = computed(() =>
  props.data.targets.map((v) => v.toFixed(2)).join(" / ")
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

const toPercent = (value: number) =>
  new Intl.NumberFormat("zh-CN", {
    style: "percent",
    minimumFractionDigits: 0,
  }).format(value);

const shortSummaryHtml = computed(() => renderMarkdown(props.data.ai_short_term_summary));
const longSummaryHtml = computed(() => renderMarkdown(props.data.ai_long_term_summary));

function renderMarkdown(content?: string | null): string {
  if (!content) return "";
  const escaped = content
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  const lines = escaped.split(/\r?\n/);
  const items: string[] = [];
  const paragraphs: string[] = [];

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (/^[-*+]\s+/.test(trimmed)) {
      items.push(`<li>${trimmed.replace(/^[-*+]\s+/, "")}</li>`);
    } else if (/^\d+\.\s+/.test(trimmed)) {
      items.push(`<li>${trimmed.replace(/^\d+\.\s+/, "")}</li>`);
    } else {
      paragraphs.push(trimmed.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>"));
    }
  }

  const parts: string[] = [];
  if (items.length) {
    parts.push(`<ul>${items.join("\n")}</ul>`);
  }
  if (paragraphs.length) {
    parts.push(paragraphs.map((p) => `<p>${p}</p>`).join(""));
  }
  return parts.join("" || "");
}
</script>

<style scoped>
.card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 10px 25px rgba(15, 23, 42, 0.06);
  padding: 1.5rem;
  margin-top: 1.5rem;
}

.card__header {
  margin-bottom: 1.5rem;
}

.grid {
  display: grid;
  gap: 1.5rem;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.headline {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.muted {
  color: #64748b;
}

.report {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 1rem;
  white-space: pre-wrap;
}

.ai-block {
  background: #f8fafc;
  border-left: 4px solid #2563eb;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  color: #0f172a;
  line-height: 1.5;
}
</style>
