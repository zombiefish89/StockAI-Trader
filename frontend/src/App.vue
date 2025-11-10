<template>
  <el-config-provider namespace="el">
    <el-container class="flex min-h-screen flex-col bg-slate-100 md:flex-row">
      <el-aside
        width="220px"
        class="flex flex-col gap-6 border-b border-slate-200 bg-white px-6 py-8 md:min-h-screen md:border-b-0 md:border-r"
      >
        <div class="space-y-1">
          <p class="text-lg font-semibold text-slate-900">StockAI Trader</p>
          <p class="text-sm text-slate-500">AI 驱动的量化助手</p>
        </div>
        <el-menu
          :default-active="activeMenu"
          class="border-transparent bg-transparent"
          @select="handleMenuSelect"
        >
          <el-menu-item
            index="/stock"
            class="rounded-xl text-slate-600 transition [&.is-active]:bg-slate-100 [&.is-active]:text-slate-900"
          >
            个股分析
          </el-menu-item>
          <el-menu-item
            index="/history"
            class="rounded-xl text-slate-600 transition [&.is-active]:bg-slate-100 [&.is-active]:text-slate-900"
          >
            分析历史
          </el-menu-item>
          <el-menu-item
            index="/reports"
            class="rounded-xl text-slate-600 transition [&.is-active]:bg-slate-100 [&.is-active]:text-slate-900"
          >
            每日报告
          </el-menu-item>
          <el-menu-item
            index="/macro"
            class="rounded-xl text-slate-600 transition [&.is-active]:bg-slate-100 [&.is-active]:text-slate-900"
          >
            宏观概览
          </el-menu-item>
          <el-menu-item
            index="/watchlist"
            class="rounded-xl text-slate-600 transition [&.is-active]:bg-slate-100 [&.is-active]:text-slate-900"
          >
            自选股
          </el-menu-item>
          <el-menu-item
            index="/opportunities"
            class="rounded-xl text-slate-600 transition [&.is-active]:bg-slate-100 [&.is-active]:text-slate-900"
          >
            机会扫描
          </el-menu-item>
        </el-menu>
      </el-aside>

      <el-container
        class="flex-1 bg-gradient-to-br from-slate-50 via-white to-indigo-50"
      >
        <el-header class="px-6 pb-4 pt-8 md:px-12 md:pb-6 md:pt-12">
          <div class="space-y-2">
            <h1 class="text-2xl font-semibold text-slate-900 md:text-3xl">
              StockAI 智能交易控制台
            </h1>
            <p class="text-sm text-slate-500 md:text-base">
              通过结构化视图快速洞察行情、板块、机会和每日简报
            </p>
          </div>
        </el-header>
        <el-main class="flex-1 px-6 pb-10 md:px-12 md:pb-14">
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </el-config-provider>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();

const activeMenu = computed(() => {
  if (route.path === "/") {
    return "/stock";
  }
  return route.path;
});

function handleMenuSelect(path: string) {
  if (path !== route.path) {
    router.push(path);
  }
}
</script>
