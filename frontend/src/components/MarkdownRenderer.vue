<template>
  <div
    v-if="sanitized && sanitized.length"
    class="markdown-body space-y-3 text-sm leading-relaxed text-slate-700"
    v-html="sanitized"
  />
  <div v-else class="text-sm text-slate-400">暂无内容</div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";

const props = defineProps<{
  content?: string | null;
}>();

const md = new MarkdownIt({
  linkify: true,
  breaks: true,
});

const sanitized = computed(() => {
  if (!props.content) return "";
  const html = md.render(props.content);
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
});
</script>
