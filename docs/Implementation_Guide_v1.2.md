# StockAI Trader v1.2 实施指南

目标：在 v1.1 基础上扩展 **宏观板块分析** 与 **机会扫描器**，帮助用户快速了解市场情绪、板块强弱，并识别自选股之外的潜在交易机会。

---

## 1. 功能拆解

1. **宏观板块分析**
   - 汇总指数与板块数据（如沪深300、纳指、恒生科技等），输出涨跌幅、成交量、资金流向。
   - 统计行业板块涨跌排名、龙头个股以及关键新闻。
   - 汇总市场情绪指标：涨跌家数、涨停/跌停、北向资金、恐慌指数等。
   - 在每日自动报告和批量分析结果中附加宏观概览。

2. **机会扫描器**
   - 对预定义的股票池或全市场（受限于数据源）进行快速筛选。
   - 根据技术指标打分，筛出做多/做空机会；支持条件（趋势、动量、量价背离等）配置。
   - 输出机会列表，对每个标的给出简短说明（信号触发原因、风险提示）。
   - 与前端联动，提供独立页面/模块展示机会池。

---

## 2. 数据与指标扩展

### 2.1 数据源
- 指数数据：依赖 yfinance / AkShare 获取主要指数日线行情。
- 板块数据：
  - A 股：AkShare 提供行业板块（如 `stock_sector_fund_flow_rank`、`stock_board_concept_name` 等）。
  - 美股/港股板块可视需求使用 yfinance ETF（如 QQQ、XLK）或自行维护配置。
- 资金流：AkShare 可获取北向资金、主力资金流排名。
- 市场情绪：可基于涨跌家数、涨停/跌停统计（AkShare）。

### 2.2 指标与评分
- 板块强弱：按 1D/5D 涨跌幅、成交量增幅、资金流排名加权。
- 宏观情绪：组合指数涨跌幅、VIX、美元指数、北向资金等。
- 机会扫描器评分：
  - 同 v1.0 的趋势/动量/回调逻辑，允许设置阈值（如动量分 > 0.5 且趋势分 > 0.3）。
  - 可针对做多/做空分别设置规则。

---

## 3. 模块设计

### 3.1 数据层 `datahub/`
- 新增 `macro.py`，提供：
  - `get_index_snapshot(symbols: List[str]) -> Dict[str, dict]`：返回主要指数的价量、涨跌幅。
  - `get_sector_rankings(market: str) -> List[dict]`：返回行业/概念板块的涨跌榜。
  - `get_market_breadth()`：统计涨跌家数、涨停/跌停数量。
  - 需缓存（与行情类似），避免频繁拉取。
- 新增 `scanner.py`：
  - 支持加载预定义股票池（可配置 JSON 或 watchlist）。
  - `scan_opportunities(tickers, timeframe="1d", limit=10) -> Dict[str, dict]`。
  - 复用 `get_candles_batch` 和 `engine.analyzer` 进行评分。

### 3.2 分析层 `engine/`
- 新增 `macro_analyzer.py`：
  - 根据 `macro.py` 提供的数据生成结构化宏观结论。
  - 输出字段示例：
    ```json
    {
      "market_overview": "...",
      "top_sectors": [{"name": "半导体", "change": 3.1, "leaders": ["台积电", "..."]}],
      "weak_sectors": [...],
      "breadth": {"advance": 2300, "decline": 1200},
      "fund_flows": {...}
    }
    ```
- 新增 `opportunity_filter.py`：
  - 实现多做多/做空筛选规则（可配置阈值、指标权重）。
  - 输出列表：每个标的包含 `ticker`, `action`, `score`, `rationale`。

### 3.3 API 层
- 添加新端点：
  - `GET /macro/overview`：返回宏观板块与市场情绪数据。
  - `POST /scanner/opportunities`：
    ```json
    {
      "tickers": ["AAPL", "MSFT"],  // 可选，默认读取 watchlist 或预设池
      "timeframe": "1d",
      "direction": "long"           // long | short | all
    }
    ```
- 在 `/watchlist/analyze` 和 `/reports` 中附加宏观概览数据，使报告更完整。

### 3.4 前端 Vue 更新
- 添加宏观仪表板组件：
  - 展示指数、情绪、板块涨跌排行榜（可参考卡片和表格形式）。
  - 支持切换市场（A 股 / 美股 / 港股）的概览。
- 新增“机会扫描器”视图：
  - 表格列示机会列表：股票、方向、置信度、触发理由、数据源。
  - 提供筛选条件（方向、时间周期、行业）。
- 在首页摘要中加入宏观概览模块。

---

## 4. 实施步骤建议

1. **数据层实现**
   - 完成 `macro.py` 与 `scanner.py`，处理数据源选择与缓存。
   - 编写单元测试确保 API 拉取和处理逻辑正确。

2. **分析与规则**
   - 实现宏观/板块分析函数，将数据转换为报告-friendly 结构。
   - 增强机会筛选规则，支持做多/做空。

3. **API 扩展**
   - 添加 `/macro/overview` 与 `/scanner/opportunities`。
   - 修改 `/reports` 生成逻辑，附加宏观概览与机会列表（可配置是否开启）。

4. **前端迭代**
   - 开发宏观面板与机会扫描组件（组件+视图+路由）。
   - 将宏观概览嵌入日报/批量分析结果展示。

5. **测试与调优**
   - 检查数据刷新频率与缓存时长（指数可 10 分钟，板块 30 分钟）。
   - 对机会筛选阈值做回测调整，避免噪音过多。
   - 验证在无数据源可用时的降级处理（如只返回 watchlist 机会）。

6. **文档与部署**
   - 更新 README 中中心功能与使用说明。
   - 若宏观数据需要额外环境变量或 API Key，在文档中说明。

---

## 5. 接口与数据结构示例

### 5.1 宏观概览响应
```json
{
  "generated_at": "2025-03-01T09:30:00+08:00",
  "indices": {
    "sh000300": {"close": 4120, "change_pct": 1.2, "turnover": 380e9},
    "nasdaq": {"close": 15280, "change_pct": -0.5}
  },
  "sectors": {
    "top": [{"name": "半导体", "change_pct": 3.1, "leaders": ["sh688981", "sh603986"]}],
    "bottom": [{"name": "煤炭", "change_pct": -2.4}]
  },
  "breadth": {"advance": 2400, "decline": 1200, "limit_up": 85, "limit_down": 12},
  "fund_flows": {"northbound": 12.5e9, "southbound": -3.2e9},
  "sentiment": {"fear_greed": 62, "volatility_index": 18.4}
}
```

### 5.2 机会扫描响应
```json
{
  "generated_at": "2025-03-01T09:35:05+08:00",
  "direction": "long",
  "timeframe": "1d",
  "candidates": [
    {
      "ticker": "AAPL",
      "score": 0.78,
      "action": "buy",
      "rationale": ["趋势与动量同步增强", "资金流入显著"],
      "data_source": "yfinance"
    },
    {
      "ticker": "sh600519",
      "score": 0.65,
      "action": "buy",
      "rationale": ["回调接近支撑，日内买盘增强"]
    }
  ]
}
```

---

## 6. 测试策略

- **单元测试**
  - 宏观数据处理函数。
  - 机会筛选逻辑，在不同阈值下的输出。

- **集成测试**
  - `GET /macro/overview` 是否返回完整结构。
  - 调度器生成的日报是否包含宏观和机会信息。

- **性能检查**
  - 批量抓取多指数、板块时的耗时。
  - 机会扫描在 100+ 股票池中完成时间是否 ≤ 60 秒。

- **前端验证**
  - 宏观与机会视图加载状态、错误处理。
  - 数据刷新频率与用户交互体验。

---

## 7. 交付与里程碑

1. 数据与分析模块完成。
2. API 端点与调度器更新。
3. 前端宏观面板与机会扫描 UI 上线。
4. README/文档更新。
5. 完成测试报告与回归。

完成上述可视为 v1.2 就绪，可根据实际反馈继续迭代数据源与筛选逻辑。

