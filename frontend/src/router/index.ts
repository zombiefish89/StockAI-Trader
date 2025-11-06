import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

const routes: RouteRecordRaw[] = [
  {
    path: "/",
    redirect: "/analysis",
  },
  {
    path: "/analysis",
    name: "analysis",
    component: () => import("../views/AnalysisView.vue"),
    meta: { label: "行情分析" },
  },
  {
    path: "/macro",
    name: "macro",
    component: () => import("../views/MacroOverviewView.vue"),
    meta: { label: "宏观概览" },
  },
  {
    path: "/watchlist",
    name: "watchlist",
    component: () => import("../views/WatchlistView.vue"),
    meta: { label: "自选股" },
  },
  {
    path: "/opportunities",
    name: "opportunities",
    component: () => import("../views/OpportunityScannerView.vue"),
    meta: { label: "机会扫描" },
  },
  {
    path: "/reports",
    name: "reports",
    component: () => import("../views/DailyReportView.vue"),
    meta: { label: "日报" },
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
