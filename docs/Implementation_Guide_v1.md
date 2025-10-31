# StockAI Trader v1.0 实施指南

## 数据源选择

- 优先选择免费的数据源。例如：  
  - 日线行情和基本财务数据：可使用 yfinance 或 AKShare 等免费 API。  
  - 实时或分钟级行情：优先选择提供免费套餐的服务商（如 Twelve Data 的免费版、IEX Cloud 免费额度），必要时再考虑付费方案。  
- 为每个数据源建立缓存策略：昨日及更早的数据缓存在本地（Parquet/SQLite），当日数据采用内存缓存并设置 TTL，减少重复请求和加快分析速度。  
- 当用户在盘中请求分析时，先检查缓存数据的新鲜度；如果缓存落后于当前时间，只抓取缺失的最新 K 线或资金数据并更新缓存，然后再进行指标计算。

## 技术分析策略

- 不使用单一固定阈值（如 RSI > 70 定义超买），而是结合趋势、动量、回调等多种信号进行综合评分。  
- 主要信号包括：  
  - **趋势类**：短期、中期、长期均线（如 EMA20、EMA50、EMA200）的排列关系；ADX 强弱；Anchored VWAP；  
  - **动量类**：MACD 金叉/死叉、RSI 分位、StochRSI 等；  
  - **回调/反转类**：KDJ 的 J 值、布林带位置、价格回踩重要支撑位等。  
- 给每类信号赋予权重（比如趋势 0.5、动量 0.3、回调/反转 0.2），对所有信号打分求和，得到综合评分并转换为买入、卖出或观望决策。  
- 通过均线、前高/前低、ATR 等确定买入价、止损价和目标价区间，确保决策有据可依。

## 技术栈与模块划分

- **数据层与分析层**：使用 Python。  
  - Python 拥有成熟的科学计算生态（pandas、numpy、ta‑lib、pandas_ta），适合处理行情数据和计算技术指标。  
  - 在 `datahub` 模块中封装数据抓取、缓存和指标计算，使用异步方式批量拉取数据。  
  - 在 `engine` 模块中实现信号打分、规则组合以及生成结构化的分析结果。  
- **应用层/API 网关**：使用 FastAPI。  
  - FastAPI 简洁高效，便于快速暴露分析接口。  
  - 提供如 `POST /analyze` 的端点，接受股票代码和时间粒度，返回结构化的分析报告。  
- **前端**：使用 Vue3 + TypeScript。  
  - 创建一个简单的 Web 界面，输入股票代码即可调用后端分析接口并展示结果。  
  - 首屏显示关键结论（操作建议、买入/止损/目标价区间、置信度），同时可展开查看详细指标及理由。  
- 将来可扩展：Node.js 作为网关或消息队列来处理并发请求；但 v1.0 MVP 阶段优先实现核心功能。

## 实施步骤概要

1. **搭建项目结构**：按照 `datahub/`、`engine/`、`api.py`、`frontend/` 等目录划分基础文件。  
2. **实现数据抓取与缓存**：  
   - 集成 yfinance 或 AKShare 获取日 K 线和必要的财务数据；  
   - 配置一个支持分钟级数据的免费源用于盘中更新；  
   - 构建缓存管理模块，支持按日期和时间刷新。  
3. **完成指标计算模块**：用 pandas‑ta 或 ta‑lib 计算 MACD、RSI、KDJ、布林带、均线、ADX、ATR 等指标。  
4. **开发规则引擎**：设计信号打分函数，将多类指标组合成综合评分，并输出买入/卖出/观望的初步结论。  
5. **生成报告**：根据综合评分和买卖区间，用模板生成简洁的中文分析报告，并在 API 接口中返回。  
6. **搭建 FastAPI 服务**：实现 `/analyze` 接口，串联数据抓取、指标计算、规则引擎和报告生成。  
7. **开发 Vue3 前端**：创建简单界面，发送请求到 FastAPI，展示报告结果。  
8. **测试与优化**：  
   - 在多只热门股票上测试分析结果和性能，确保总耗时 ≤ 60 秒；  
   - 调整缓存策略和信号权重，提高结论稳定性和准确性；  
   - 根据用户反馈迭代功能。

该文档汇总了 v1.0 MVP 的核心实施思路，可作为你开发时的指南.

## 目录结构示例
以下是一个建议的项目目录结构，用于组织数据层、分析层和接口层：

```
StockAI-Trader/
├── datahub/
│   ├── __init__.py
│   ├── fetcher.py           # 从数据源异步拉取行情和资金数据
│   ├── cache.py             # 本地缓存（Parquet/SQLite）管理
│   ├── indicators.py        # 使用 pandas_ta/ta-lib 计算技术指标
├── engine/
│   ├── __init__.py
│   ├── analyzer.py          # 整合指标，输出信号打分
│   ├── rules.py             # 组合不同类型信号的权重和决策规则
│   ├── report.py            # 将结构化结果渲染为文本报告
├── api.py                   # FastAPI 应用入口，暴露 /analyze 接口
├── frontend/                # Vue3 前端源码（可放在单独仓库）
│   ├── src/
│   │   ├── components/
│   │   ├── views/
│   │   └── ...
│   └── package.json
└── README.md
```

## 关键函数接口设计
以下是些常用函数的接口签名，便于后继编码时相互符合：

- `fetcher.get_latest_candles(ticker: str, start: datetime, end: datetime) -> pandas.DataFrame`：从数据源或缓存拉取线线数据，保证不缺流多有.
- `indicators.compute_all(df: pandas.DataFrame) -> Dict[str, float]`：在线数据上计算所有所需的指标，包括 EMA, RSI, MACD, ATR, KDJ_J, BB_pos 等，返回一个具名值对容器。
- `analyzer.score_signals(features: Dict[str, float]) -> Dict[str, float]`：根据指标特征计算趋势分、动量分、回调分，并进行标准化和带权求和。
- `rules.generate_decision(scores: Dict[str, float], price_info: Dict[str, float]) -> Dict`：根据信号打分和当前价格信息，判定算略方向（走多/做空/观望）和建议的进场价、止损价和目标价区间。
- `report.render(decision: Dict) -> str`：将决策和论据结构化结果转化成自然语言的文本报告，包含判方利容与风险提示。

## API 接口示例
这里给出 FastAPI 接口的积参和回应格式，便于前后端延传和自动代码生成。

- **请求**：`POST /analyze`
  - **body**（JSON）：
    ```json
    {
      "ticker": "HOOD",
      "timeframe": "1d",        // 时间分类：1m/5m/1h/1d
      "start": "2025-10-01",    // 可选，传入准备的起始日期
      "end": "2025-10-31"        // 可选，结束日期
    }
    ```
- **响应**（JSON）：
    ```json
    {
      "ticker": "HOOD",
      "as_of": "2025-10-31T14:12:00+09:00",
      "action": "buy",               // buy | sell | hold
      "entry": 145.5,
      "stop": 135.0,
      "targets": [152, 155],
      "confidence": 0.72,
      "signals": {
        "trend": {"ema20_above_50": true, "adx": 24.1, "anchored_vwap_ok": true},
        "momentum": {"rsi": 68.3, "zscore_rsi": 1.4, "macd_cross": "bullish"},
        "revert": {"bb_position": 0.78, "kdj_j": 102.2}
      },
      "rationale": [
        "\u591a\u5934\u73af\u5883\u786e\u7acb (EMA20>EMA50>EMA200, ADX>20)",
        "\u52a8\u91cf\u5f3a\uff0c\u4f46 RSI \u5206\u4f4d\u504f\u9ad8\uff0c\u77ed\u7ebf\u6709\u56de\u843d\u6982\u7387",
        "\u5efa\u8bae\u56de\u8e29 MA20/\u524d\u9ad8\u9644\u8fd1\u4f4e\u5438\uff0c\u5206\u6279\u6b62\u76ca"
      ],
      "risk_notes": ["\u77ed\u7ebf\u8d85\u4e70", "\u5982\u653e\u91cf\u8dcc\u7834 MA20 \u9700\u51cf\u4ed3\u6216\u64a4\u9000"],
      "latency_ms": 640
    }
    ```

## 信号打分例码
下面是一个简单的信号打分代码示例，帮助 Codex 快速理解怎么计算自动分值。

```python
# 环境过滤
bull_env = (ema20 > ema50 > ema200) and (adx > 20) and (price > anchored_vwap_month)

# 动量打分
mom_score = 0.0
if macd_cross == "bullish":
    mom_score += 0.5
elif macd_cross == "bearish":
    mom_score -= 0.5

# RSI 标准分值对自身历史进行 zscore
if rsi_zscore < 1.0:
    mom_score += 0.3
elif rsi_zscore > 2.0:
    mom_score -= 0.2

# 回调信号
revert_score = 0.0
if 0.4 <= bb_pos <= 0.6:
    revert_score += 0.3  # 近中或下轮保质点
elif bb_pos > 0.9:
    revert_score -= 0.2

if kdj_j < 90:
    revert_score += 0.2
elif kdj_j > 110:
    revert_score -= 0.2

# 总分
score = 0.5 * (1 if bull_env else -1) + 0.3 * mom_score + 0.2 * revert_score

# 根据总分定义操作
if score > 0.4:
    action = "buy"
elif score < -0.4:
    action = "sell"
else:
    action = "hold"

# 价位计算可以采用 ATR 和前高/MA20 来计算 entry, stop, target
```

## 缓存更新逻辑

1. **常驻数据**：将日线和上一个平短周的分钟线数据提前打包保存到 Parquet/SQLite，设置 TTL (24h我0月)。
2. **新鲜数据**：在用户发起分析时，先检查缓存中最后一条 K 线的时间戳，如果与当前时间相差超过预定间隔（例如 1 分钟），则只拉取此缺句范围内的新数据，更新缓存。
3. **微步减能**：算指标时只重算发生变化的线数据缓血理线数据缓缓存数据分析数据后复盘。
4. **异步拉取**：如果在本次分析中需要不同时间段或多种数据源，可将 fetcher 函数进行异步执行，提高总体响较性能。
  
