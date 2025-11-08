<template>
  <el-card
    shadow="never"
    class="rounded-2xl border border-amber-200/70 bg-amber-50/70"
  >
    <template #header>
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-semibold text-amber-800">风险提示</h3>
        <el-tag size="small" type="warning" class="rounded-full">重点关注</el-tag>
      </div>
    </template>
    <ul class="space-y-3">
      <li
        v-for="(item, index) in items"
        :key="index"
        class="rounded-xl border border-amber-200/70 bg-white/90 px-4 py-3 text-sm leading-relaxed text-amber-900 shadow-sm"
      >
        {{ item }}
      </li>
    </ul>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  items: string[];
}>();
</script>
