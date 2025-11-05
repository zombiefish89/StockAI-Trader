"""
多级缓存适配器：Redis (L1) / MongoDB (L2) / 本地文件 (L3)。

Redis 与 Mongo 的启用与参数均由 .env 控制，TTL 参考 TradingAgents-CN
的分层策略。缓存内容统一以 JSON (orient=split) 序列化，以便快速回读为 DataFrame。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Optional

import pandas as pd

try:  # pragma: no cover - 可选依赖
    import redis  # type: ignore
except ImportError:  # pragma: no cover
    redis = None  # type: ignore

try:  # pragma: no cover - 可选依赖
    from pymongo import MongoClient  # type: ignore
    from pymongo.errors import PyMongoError  # type: ignore
except ImportError:  # pragma: no cover
    MongoClient = None  # type: ignore
    PyMongoError = Exception  # type: ignore

from datahub.cache import DataCache

logger = logging.getLogger(__name__)


def _parse_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _parse_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class RedisAdapter:
    """Redis L1 缓存适配器。"""

    def __init__(self) -> None:
        self.enabled = _parse_bool("REDIS_ENABLED", False)
        self.client = None
        if not self.enabled:
            return
        if redis is None:
            logger.warning("启用了 REDIS_ENABLED，但未安装 redis 库。")
            self.enabled = False
            return
        host = os.getenv("REDIS_HOST", "127.0.0.1")
        port = _parse_int("REDIS_PORT", 6379)
        db_index = _parse_int("REDIS_DB", 0)
        try:
            self.client = redis.Redis(host=host, port=port, db=db_index)  # type: ignore[arg-type]
            self.client.ping()
        except Exception as exc:  # pragma: no cover - 远程不可达
            logger.warning("Redis 不可用，已禁用：%s", exc)
            self.client = None
            self.enabled = False

    def get(self, key: str) -> Optional[str]:
        if not self.enabled or self.client is None:
            return None
        try:
            raw = self.client.get(key)
            if raw is None:
                return None
            if isinstance(raw, bytes):
                return raw.decode("utf-8")
            return str(raw)
        except Exception as exc:  # pragma: no cover
            logger.debug("Redis 读取失败 %s: %s", key, exc)
            return None

    def set(self, key: str, payload: str, ttl: int) -> None:
        if not self.enabled or self.client is None:
            return
        try:
            self.client.setex(key, ttl, payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("Redis 写入失败 %s: %s", key, exc)


class MongoAdapter:
    """MongoDB L2 缓存适配器。"""

    def __init__(self) -> None:
        self.enabled = _parse_bool("MONGO_ENABLED", False)
        self.collection = None
        if not self.enabled:
            return
        if MongoClient is None:
            logger.warning("启用了 MONGO_ENABLED，但未安装 pymongo。")
            self.enabled = False
            return
        uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        db_name = os.getenv("MONGO_DB", "stockai_cache")
        coll_name = os.getenv("MONGO_COLLECTION", "timeseries_cache")
        try:
            client = MongoClient(uri, serverSelectionTimeoutMS=2000)  # type: ignore[arg-type]
            # 触发一次 server selection
            client.admin.command("ping")
            self.collection = client[db_name][coll_name]
            self.collection.create_index("expires_at", expireAfterSeconds=0)
        except Exception as exc:  # pragma: no cover - 远程不可达
            logger.warning("MongoDB 不可用，已禁用：%s", exc)
            self.collection = None
            self.enabled = False

    def get(self, key: str) -> Optional[str]:
        if not self.enabled or self.collection is None:
            return None
        try:
            doc = self.collection.find_one({"_id": key})
        except PyMongoError as exc:  # pragma: no cover
            logger.debug("MongoDB 读取失败 %s: %s", key, exc)
            return None
        if not doc:
            return None
        expires_at = doc.get("expires_at")
        if isinstance(expires_at, datetime) and expires_at < datetime.now(timezone.utc):
            try:
                self.collection.delete_one({"_id": key})
            except PyMongoError:
                pass
            return None
        return doc.get("payload")

    def set(self, key: str, payload: str, ttl: int) -> None:
        if not self.enabled or self.collection is None:
            return
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        doc = {"payload": payload, "expires_at": expires_at}
        try:
            self.collection.update_one({"_id": key}, {"$set": doc}, upsert=True)
        except PyMongoError as exc:  # pragma: no cover
            logger.debug("MongoDB 写入失败 %s: %s", key, exc)


class CacheManager:
    """统一的缓存管理器。"""

    def __init__(self) -> None:
        self.enabled = _parse_bool("CACHE_ENABLED", True)
        self.redis = RedisAdapter()
        self.mongo = MongoAdapter()
        base_dir = os.getenv("CACHE_DIR", "./cache")
        self.file_cache = DataCache(base_dir=base_dir)

        self.ttl_quote_fast = _parse_int("TTL_QUOTE_FAST", 30)
        self.ttl_intraday = _parse_int("TTL_INTRADAY", 60)
        self.ttl_daily = _parse_int("TTL_DAILY", 3600)
        self.ttl_fundamental = _parse_int("TTL_FUNDAMENTAL", 21600)

    def ttl_for_interval(self, interval: str) -> int:
        interval = (interval or "").lower()
        if interval in {"tick", "1s"}:
            return self.ttl_quote_fast
        if interval in {"1m", "5m", "15m", "30m"}:
            return self.ttl_intraday
        if interval in {"1h", "2h", "4h"}:
            return max(self.ttl_intraday, 300)
        return self.ttl_daily

    def make_key(self, provider: str, ticker: str, interval: str) -> str:
        return f"{provider.lower()}::{ticker.upper()}::{interval.lower()}"

    def load_json(self, key: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        payload = self.redis.get(key)
        if payload is None:
            payload = self.mongo.get(key)
        if payload is None:
            return None
        try:
            return json.loads(payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("JSON 缓存反序列化失败 %s: %s", key, exc)
            return None

    def store_json(self, key: str, payload: Dict[str, Any], ttl: int) -> None:
        if not self.enabled or ttl <= 0:
            return
        try:
            text = json.dumps(payload, ensure_ascii=False)
        except Exception as exc:  # pragma: no cover
            logger.debug("JSON 序列化失败 %s: %s", key, exc)
            return
        self.redis.set(key, text, ttl)
        self.mongo.set(key, text, ttl)

    def load_dataframe(self, provider: str, ticker: str, interval: str) -> Optional[pd.DataFrame]:
        if not self.enabled:
            return None
        key = self.make_key(provider, ticker, interval)
        payload = self.redis.get(key)
        if payload is None:
            payload = self.mongo.get(key)
        if payload is None:
            return None
        try:
            return self._deserialize(payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("缓存反序列化失败 %s: %s", key, exc)
            return None

    def store_dataframe(
        self,
        provider: str,
        ticker: str,
        interval: str,
        df: pd.DataFrame,
        *,
        ttl: Optional[int] = None,
    ) -> None:
        if not self.enabled or df is None or df.empty:
            return
        ttl_value = ttl if ttl is not None else self.ttl_for_interval(interval)
        if ttl_value <= 0:
            return
        payload = self._serialize(df)
        key = self.make_key(provider, ticker, interval)
        self.redis.set(key, payload, ttl_value)
        self.mongo.set(key, payload, ttl_value)

    @staticmethod
    def _serialize(df: pd.DataFrame) -> str:
        return df.to_json(orient="split", date_format="iso")

    @staticmethod
    def _deserialize(payload: str) -> pd.DataFrame:
        return pd.read_json(StringIO(payload), orient="split")


cache_manager = CacheManager()
