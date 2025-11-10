import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
} from "vue-router";

const routes: RouteRecordRaw[] = [
  {
    path: "/",
    redirect: "/stock",
  },
  {
    path: "/stock",
    name: "stock",
    component: () => import("../views/StockAnalysisView.vue"),
    meta: { label: "个股分析" },
  },
  {
    path: "/history",
    name: "history",
    component: () => import("../views/AnalysisHistoryView.vue"),
    meta: { label: "分析历史" },
  },
  {
    path: "/reports",
    name: "reports",
    component: () => import("../views/DailyReportView.vue"),
    meta: { label: "日报" },
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
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
