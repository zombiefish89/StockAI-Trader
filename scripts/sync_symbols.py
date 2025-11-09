"""同步全市场股票代码到 MongoDB / 本地快照。"""

from __future__ import annotations
from requests import RequestException
import requests

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

# 将项目根目录加入 sys.path，便于复用现有模块
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import env  # noqa: F401


try:  # pragma: no cover - 可选依赖
    import akshare as ak  # type: ignore
except Exception:  # pragma: no cover - 未安装 AkShare 也可继续
    ak = None  # type: ignore

try:
    from pymongo import MongoClient, UpdateOne  # type: ignore
    from pymongo.errors import PyMongoError  # type: ignore
except Exception:  # pragma: no cover
    MongoClient = None  # type: ignore
    UpdateOne = None  # type: ignore
    PyMongoError = Exception  # type: ignore

from datahub.tushare_api import (  # noqa: E402
    TushareUnavailable,
    fetch_stock_basic,
    get_pro,
)

logger = logging.getLogger(__name__)

MARKET_ORDER = {"cn": 0, "hk": 1, "us": 2}
_PROXY_CLEARED = False


def _lazy_pinyin(value: Optional[str]) -> tuple[str, str]:
    if not value:
        return "", ""
    try:
        from pypinyin import lazy_pinyin  # type: ignore
    except Exception:  # pragma: no cover - 可选依赖
        return "", ""
    tokens = lazy_pinyin(value)
    if not tokens:
        return "", ""
    full = " ".join(tokens)
    abbr = "".join(token[0] for token in tokens if token)
    return full, abbr


def _normalize_aliases(values: Iterable[Optional[str]]) -> List[str]:
    aliases: List[str] = []
    for value in values:
        if not value:
            continue
        text = str(value).strip()
        if not text:
            continue
        if text not in aliases:
            aliases.append(text)
    return aliases


def _disable_http_proxy() -> None:
    global _PROXY_CLEARED
    if _PROXY_CLEARED:
        return
    removed = False
    for key in [
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
        "socks_proxy",
        "SOCKS_PROXY",
    ]:
        if key in os.environ:
            os.environ.pop(key, None)
            removed = True
    if removed:
        os.environ.setdefault("NO_PROXY", "*")
    _PROXY_CLEARED = True


@dataclass
class SymbolRecord:
    ticker: str
    market: str
    exchange: Optional[str] = None
    name_cn: Optional[str] = None
    name_en: Optional[str] = None
    display_name: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    rank: int = 0
    pinyin_full: Optional[str] = None
    pinyin_abbr: Optional[str] = None

    def finalize(self) -> None:
        self.ticker = (self.ticker or "").upper()
        if not self.display_name:
            self.display_name = self.name_cn or self.name_en or self.ticker
        full, abbr = _lazy_pinyin(self.name_cn)
        if full:
            self.pinyin_full = full
        if abbr:
            self.pinyin_abbr = abbr
        self.aliases = _normalize_aliases(
            [self.ticker, self.display_name, self.name_cn, self.name_en,
                *self.aliases, self.pinyin_full, self.pinyin_abbr]
        )

    def to_document(self, timestamp: datetime) -> Dict[str, object]:
        search_tokens = _normalize_aliases(
            [
                self.ticker,
                self.display_name,
                self.name_cn,
                self.name_en,
                *self.aliases,
                self.pinyin_full,
                self.pinyin_abbr,
            ]
        )
        search_text = " ".join(search_tokens)
        return {
            "_id": self.ticker,
            "ticker": self.ticker,
            "market": self.market,
            "exchange": self.exchange,
            "name_cn": self.name_cn,
            "name_en": self.name_en,
            "display_name": self.display_name,
            "aliases": self.aliases,
            "pinyin_full": self.pinyin_full,
            "pinyin_abbr": self.pinyin_abbr,
            "search_text": search_text,
            "rank": self.rank,
            "updated_at": timestamp,
        }

    def to_snapshot(self) -> Dict[str, object]:
        return {
            "ticker": self.ticker,
            "display_name": self.display_name,
            "name_cn": self.name_cn,
            "name_en": self.name_en,
            "market": self.market,
            "exchange": self.exchange,
            "aliases": self.aliases,
            "pinyin_full": self.pinyin_full,
            "pinyin_abbr": self.pinyin_abbr,
            "rank": self.rank,
        }


def load_cn_symbols(limit: Optional[int] = None) -> List[SymbolRecord]:
    try:
        df = fetch_stock_basic(
            fields="ts_code,symbol,name,fullname,enname,market,exchange,list_date"
        )
    except TushareUnavailable as exc:
        logger.warning("Tushare 不可用，跳过 A 股拉取：%s", exc)
        return []
    if df is None or df.empty:
        logger.warning("Tushare stock_basic 返回为空。")
        return []
    records: List[SymbolRecord] = []
    iterable = df.itertuples(index=False)
    count = 0
    for row in iterable:
        ticker = str(getattr(row, "ts_code", "")).upper()
        if not ticker:
            continue
        name_cn = getattr(row, "name", None)
        name_en = getattr(row, "enname", None)
        exchange = getattr(row, "exchange", None)
        symbol = getattr(row, "symbol", None)
        fullname = getattr(row, "fullname", None)
        record = SymbolRecord(
            ticker=ticker,
            market="cn",
            exchange=str(exchange).upper() if exchange else None,
            name_cn=name_cn,
            name_en=name_en,
            display_name=name_cn or fullname or ticker,
            aliases=[ticker, symbol, fullname],
        )
        record.finalize()
        records.append(record)
        count += 1
        if limit and count >= limit:
            break
    logger.info("加载 A 股标的 %s 条。", len(records))
    return records


def load_hk_symbols(limit: Optional[int] = None) -> List[SymbolRecord]:
    records = _load_hk_from_tushare(limit)
    if records:
        return records
    fallback = _load_hk_from_akshare(limit)
    if fallback:
        logger.info("Tushare 港股数据不可用，已使用 AkShare 降级。")
    return fallback


def _load_hk_from_akshare(limit: Optional[int]) -> List[SymbolRecord]:
    if ak is None:
        return []
    _disable_http_proxy()
    try:
        df = ak.stock_hk_spot_em()  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - 外部接口异常
        logger.warning("AkShare 获取港股列表失败：%s", exc)
        return []
    if df is None or df.empty:
        return []
    records: List[SymbolRecord] = []
    count = 0
    for _, row in df.iterrows():
        code = str(row.get("代码") or row.get("code") or "").strip()
        name_cn = row.get("名称") or row.get("name")
        if not code:
            continue
        ticker = f"{int(code):05d}.HK"
        record = SymbolRecord(
            ticker=ticker,
            market="hk",
            exchange="HKEX",
            name_cn=name_cn,
            name_en=row.get("英文名称") or row.get("engname"),
            display_name=name_cn or ticker,
            aliases=[code, ticker, name_cn, row.get("英文名称")],
        )
        record.finalize()
        records.append(record)
        count += 1
        if limit and count >= limit:
            break
    logger.info("加载港股标的 %s 条。", len(records))
    return records


def _load_hk_from_tushare(limit: Optional[int]) -> List[SymbolRecord]:
    try:
        pro = get_pro()
    except TushareUnavailable as exc:
        logger.warning("Tushare 不可用，无法拉取港股列表：%s", exc)
        return []
    try:
        df = pro.hk_basic(
            list_status="L", fields="ts_code,name,fullname,enname,list_date,exchange")
    except Exception as exc:  # pragma: no cover - 外部接口异常
        logger.warning("Tushare hk_basic 请求失败：%s", exc)
        return []
    if df is None or df.empty:
        logger.warning("Tushare hk_basic 返回为空。")
        return []
    records: List[SymbolRecord] = []
    count = 0
    for row in df.itertuples(index=False):
        ticker = str(getattr(row, "ts_code", "")).upper()
        if not ticker:
            continue
        name_cn = getattr(row, "name", None)
        full_name = getattr(row, "fullname", None)
        name_en = getattr(row, "enname", None)
        exchange = getattr(row, "exchange", None)
        record = SymbolRecord(
            ticker=ticker,
            market="hk",
            exchange=str(exchange).upper() if exchange else "HKEX",
            name_cn=name_cn,
            name_en=name_en,
            display_name=name_cn or full_name or ticker,
            aliases=[ticker, name_cn, full_name, name_en],
        )
        record.finalize()
        records.append(record)
        count += 1
        if limit and count >= limit:
            break
    logger.info("使用 Tushare 加载港股标的 %s 条。", len(records))
    return records


def load_us_symbols(limit: Optional[int] = None) -> List[SymbolRecord]:
    records_map = _load_us_from_tushare(limit)
    _enrich_us_symbols_with_finnhub(records_map, limit)
    _patch_us_cn_names_from_eastmoney(records_map, limit)
    logger.info("加载美股标的 %s 条。", len(records_map))
    return list(records_map.values())


def _normalize_us_ticker(ts_code: Optional[str]) -> Optional[str]:
    if not ts_code:
        return None
    raw = ts_code.strip().upper()
    if not raw:
        return None
    if "." in raw:
        return raw.split(".", 1)[0]
    return raw


def _load_us_from_tushare(limit: Optional[int]) -> Dict[str, SymbolRecord]:
    records: Dict[str, SymbolRecord] = {}
    try:
        pro = get_pro()
    except TushareUnavailable as exc:
        logger.warning("Tushare 不可用，无法拉取美股列表：%s", exc)
        return records

    try:
        df = pro.us_basic(
            list_status="L",
            fields="ts_code,name,enname,fullname,list_date,exchange",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Tushare us_basic 请求失败：%s", exc)
        return records

    if df is None or df.empty:
        logger.warning("Tushare us_basic 返回为空。")
        return records

    for row in df.itertuples(index=False):
        raw_code = getattr(row, "ts_code", None)
        ticker = _normalize_us_ticker(raw_code)
        if not ticker:
            continue
        name_cn = getattr(row, "name", None)
        name_en = getattr(row, "enname", None)
        full_name = getattr(row, "fullname", None)
        exchange = getattr(row, "exchange", None)
        aliases = [ticker, raw_code, name_cn, name_en, full_name]

        existing = records.get(ticker)
        if existing:
            dirty = False
            if name_cn and not existing.name_cn:
                existing.name_cn = name_cn
                dirty = True
            if name_en and not existing.name_en:
                existing.name_en = name_en
                dirty = True
            if name_cn:
                existing.display_name = name_cn
            if exchange and not existing.exchange:
                existing.exchange = str(exchange).upper()
            existing.aliases = _normalize_aliases(
                [*existing.aliases, *aliases])
            if dirty or name_cn:
                existing.finalize()
            continue

        if limit and len(records) >= limit:
            break
        record = SymbolRecord(
            ticker=ticker,
            market="us",
            exchange=str(exchange).upper() if exchange else "US",
            name_cn=name_cn,
            name_en=name_en or full_name,
            display_name=name_cn or full_name or name_en or ticker,
            aliases=aliases,
        )
        record.finalize()
        records[ticker] = record
    logger.info("使用 Tushare 加载美股标的 %s 条。", len(records))
    return records


def _enrich_us_symbols_with_finnhub(records: Dict[str, SymbolRecord], limit: Optional[int]) -> None:
    token = os.getenv("FINNHUB_API_KEY")
    if not token:
        logger.warning("缺少 FINNHUB_API_KEY，跳过 Finnhub 美股列表。")
        return
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/stock/symbol",
            params={"exchange": "US", "token": token},
            timeout=30,
        )
        resp.raise_for_status()
    except RequestException as exc:  # pragma: no cover
        logger.warning("Finnhub 拉取美股失败：%s", exc)
        return
    try:
        payload = resp.json()
    except ValueError as exc:  # pragma: no cover
        logger.warning("Finnhub 响应解析失败：%s", exc)
        return

    additions = 0
    for item in payload:
        symbol = str(item.get("symbol") or item.get(
            "displaySymbol") or "").upper()
        description = item.get("description")
        if not symbol or not description:
            continue
        if not symbol.isalpha():
            continue
        if symbol in records:
            existing = records[symbol]
            if not existing.name_en:
                existing.name_en = description
            existing.aliases = _normalize_aliases(
                [*existing.aliases, description])
            continue
        if limit and len(records) >= limit:
            break
        record = SymbolRecord(
            ticker=symbol,
            market="us",
            exchange=item.get("mic") or item.get("exchange") or "US",
            name_en=description,
            display_name=description,
            aliases=[symbol, item.get("displaySymbol"), description],
        )
        record.finalize()
        records[symbol] = record
        additions += 1

    if additions:
        logger.info("使用 Finnhub 追加美股标的 %s 条。", additions)


def _patch_us_cn_names_from_eastmoney(records: Dict[str, SymbolRecord], limit: Optional[int]) -> None:
    if not records:
        return
    cn_map = _fetch_us_cn_names_from_eastmoney(limit)
    if not cn_map:
        return
    patched = 0
    for ticker, cn_name in cn_map.items():
        record = records.get(ticker)
        if record is None:
            continue
        if record.name_cn == cn_name:
            continue
        record.name_cn = cn_name
        record.display_name = cn_name or record.display_name
        record.aliases = _normalize_aliases([*record.aliases, cn_name])
        record.finalize()
        patched += 1
    if patched:
        logger.info("使用 东财 美股列表补充中文名 %s 条。", patched)


def _fetch_us_cn_names_from_eastmoney(limit: Optional[int]) -> Dict[str, str]:
    _disable_http_proxy()
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quote.eastmoney.com/",
    }
    pz = 200
    page = 1
    total: Dict[str, str] = {}
    while True:
        params = {
            "pn": page,
            "pz": pz,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f12",
            "fs": "m:105,m:106,m:107",
            "fields": "f12,f14",
        }
        try:
            resp = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=10,
                proxies={"http": None, "https": None},
            )
            resp.raise_for_status()
        except RequestException as exc:  # pragma: no cover - 网络异常
            logger.warning("东财美股列表请求失败：%s", exc)
            return {}
        data = resp.json()
        diff = (data.get("data") or {}).get("diff") or []
        if not diff:
            break
        for row in diff:
            code = str(row.get("f12") or "").upper()
            name = row.get("f14")
            if not code or not name:
                continue
            total[code] = str(name).strip()
            if limit and len(total) >= limit:
                break
        if (limit and len(total) >= limit) or len(diff) < pz:
            break
        page += 1
    if not total:
        logger.warning("东财美股列表返回为空。")
    return total


def assign_ranks(records: List[SymbolRecord]) -> None:
    records.sort(key=lambda item: (MARKET_ORDER.get(
        item.market, 99), item.display_name or item.ticker))
    for idx, record in enumerate(records, start=1):
        record.rank = idx


def write_snapshot(records: Sequence[SymbolRecord], snapshot_path: Path) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [record.to_snapshot() for record in records]
    snapshot_path.write_text(json.dumps(
        payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("已写入本地快照：%s", snapshot_path)


def upsert_mongo(records: Sequence[SymbolRecord], uri: str, db: str, coll: str) -> None:
    if MongoClient is None or UpdateOne is None:
        logger.warning("未安装 pymongo，跳过 Mongo 同步。")
        return
    client = MongoClient(uri)
    collection = client[db][coll]
    ops: List[UpdateOne] = []
    timestamp = datetime.now(timezone.utc)
    for record in records:
        ops.append(UpdateOne({"_id": record.ticker}, {
                   "$set": record.to_document(timestamp)}, upsert=True))
    if ops:
        try:
            collection.bulk_write(ops, ordered=False)
        except PyMongoError as exc:  # pragma: no cover
            logger.error("写入 Mongo 失败：%s", exc)
            return
    try:
        collection.create_index("ticker", unique=True)
        collection.create_index([("market", 1), ("rank", 1)])
        collection.create_index(
            [
                ("display_name", "text"),
                ("name_cn", "text"),
                ("name_en", "text"),
                ("aliases", "text"),
                ("search_text", "text"),
                ("pinyin_full", "text"),
                ("pinyin_abbr", "text"),
            ],
            name="symbol_text_idx",
            default_language="none",
        )
    except PyMongoError as exc:  # pragma: no cover
        logger.warning("创建索引失败：%s", exc)
    logger.info("MongoDB 同步完成，写入 %s 条记录。", len(records))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步 A/HK/US 股票代码供前端检索。")
    parser.add_argument(
        "--markets",
        nargs="+",
        choices=["cn", "hk", "us"],
        default=["cn", "hk", "us"],
        help="需要同步的市场，默认全部。",
    )
    parser.add_argument("--snapshot", type=Path, default=Path(
        os.getenv("SYMBOL_SNAPSHOT_PATH", "data/symbols_snapshot.json")))
    parser.add_argument("--cn-limit", type=int, help="仅用于调试时限制 A 股条数")
    parser.add_argument("--hk-limit", type=int, help="仅用于调试时限制 港股条数")
    parser.add_argument("--us-limit", type=int, help="仅用于调试时限制 美股条数")
    parser.add_argument("--skip-mongo", action="store_true",
                        help="仅生成快照，不写 MongoDB")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()

    records: List[SymbolRecord] = []
    if "cn" in args.markets:
        records.extend(load_cn_symbols(limit=args.cn_limit))
    if "hk" in args.markets:
        records.extend(load_hk_symbols(limit=args.hk_limit))
    if "us" in args.markets:
        records.extend(load_us_symbols(limit=args.us_limit))

    if not records:
        logger.error("未获取到任何标的，终止。")
        sys.exit(1)

    # 去重：后写入的市场覆盖前者
    unique: Dict[str, SymbolRecord] = {}
    for record in records:
        unique[record.ticker] = record
    deduped = list(unique.values())

    assign_ranks(deduped)
    write_snapshot(deduped, args.snapshot)

    if args.skip_mongo:
        logger.info("已按照 --skip-mongo 参数跳过 MongoDB 写入。")
        return

    uri = os.getenv("SYMBOLS_MONGO_URI", os.getenv(
        "MONGO_URI", "mongodb://localhost:27017"))
    db = os.getenv("SYMBOLS_MONGO_DB", os.getenv("MONGO_DB", "stockai_cache"))
    coll = os.getenv("SYMBOLS_MONGO_COLLECTION", "symbols_lookup")
    upsert_mongo(deduped, uri, db, coll)


if __name__ == "__main__":
    main()
