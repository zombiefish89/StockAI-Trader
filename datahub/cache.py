"""
基于文件的行情数据缓存工具。

在可用时优先使用 Parquet 存储 pandas DataFrame；若缺少 pyarrow，
则退化为 CSV。缓存按股票与时间粒度区分，并通过 TTL 校验有效期。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class DataCache:
    """用于表格行情数据的简易文件缓存。"""

    def __init__(self, base_dir: Path | str = "cache", ttl_seconds: int = 60 * 60 * 24):
        self.base_dir = Path(base_dir)
        self.ttl_seconds = ttl_seconds
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _base_path(self, ticker: str, timeframe: str, provider: str) -> Path:
        safe_ticker = ticker.replace("/", "_").upper()
        safe_provider = provider.replace("/", "_").lower()
        return self.base_dir / safe_provider / timeframe / safe_ticker

    def _legacy_base_path(self, ticker: str, timeframe: str) -> Path:
        safe_ticker = ticker.replace("/", "_").upper()
        return self.base_dir / timeframe / safe_ticker

    def _primary_path(self, ticker: str, timeframe: str, provider: str) -> Path:
        return self._base_path(ticker, timeframe, provider).with_suffix(".parquet")

    def _fallback_path(self, ticker: str, timeframe: str, provider: str) -> Path:
        return self._base_path(ticker, timeframe, provider).with_suffix(".csv")

    def _metadata_path(self, ticker: str, timeframe: str, provider: str) -> Path:
        return self._base_path(ticker, timeframe, provider).with_suffix(".meta")

    def load(self, ticker: str, timeframe: str, provider: str = "default") -> Optional[pd.DataFrame]:
        """加载指定提供方的缓存数据。"""
        path = self._primary_path(ticker, timeframe, provider)
        csv_path = self._fallback_path(ticker, timeframe, provider)

        if not path.exists() and not csv_path.exists():
            # 兼容旧版缓存目录结构
            legacy_path = self._legacy_base_path(ticker, timeframe).with_suffix(".parquet")
            legacy_csv = self._legacy_base_path(ticker, timeframe).with_suffix(".csv")
            if legacy_path.exists():
                path = legacy_path
            elif legacy_csv.exists():
                csv_path = legacy_csv
            else:
                return None

        if self.is_stale(ticker, timeframe, provider):
            return None

        if path.exists():
            return self._read_dataframe(path)
        return self._read_dataframe(csv_path)

    def store(self, ticker: str, timeframe: str, df: pd.DataFrame, provider: str = "default") -> None:
        """写入 DataFrame 并记录缓存时间戳。"""
        if df.empty:
            logger.debug("跳过缓存空数据：%s %s (%s)", ticker, timeframe, provider)
            return

        parquet_path = self._primary_path(ticker, timeframe, provider)
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        wrote = self._write_dataframe(parquet_path, df)
        if not wrote:
            csv_path = self._fallback_path(ticker, timeframe, provider)
            df.to_csv(csv_path)

        metadata_path = self._metadata_path(ticker, timeframe, provider)
        metadata = {"cached_at": int(time.time()), "provider": provider, "rows": int(len(df))}
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    def is_stale(self, ticker: str, timeframe: str, provider: str = "default") -> bool:
        """判断缓存是否过期或不存在。"""
        metadata_path = self._metadata_path(ticker, timeframe, provider)
        if not metadata_path.exists():
            legacy_meta = self._legacy_base_path(ticker, timeframe).with_suffix(".meta")
            metadata_path = legacy_meta
            if not metadata_path.exists():
                return True
        try:
            raw = metadata_path.read_text(encoding="utf-8")
            if raw.strip().isdigit():
                cached_at = int(raw.strip())
            else:
                cached_at = int(json.loads(raw).get("cached_at", 0))
        except Exception:
            logger.warning("缓存元信息损坏：%s %s (%s)", ticker, timeframe, provider)
            return True
        age = time.time() - cached_at
        return age >= self.ttl_seconds

    def clear(self, ticker: str, timeframe: str, provider: str = "default") -> None:
        """清理指定提供方的缓存文件。"""
        metadata_path = self._metadata_path(ticker, timeframe, provider)
        path = self._primary_path(ticker, timeframe, provider)
        for target in (path, metadata_path):
            if target.exists():
                target.unlink()
        csv_path = self._fallback_path(ticker, timeframe, provider)
        if csv_path.exists():
            csv_path.unlink()

        # 同步清理历史目录
        legacy_base = self._legacy_base_path(ticker, timeframe)
        for suffix in (".parquet", ".csv", ".meta"):
            legacy_file = legacy_base.with_suffix(suffix)
            if legacy_file.exists():
                legacy_file.unlink()

    @staticmethod
    def _read_dataframe(path: Path) -> pd.DataFrame:
        if path.suffix == ".parquet":
            try:
                return pd.read_parquet(path)
            except Exception as exc:  # pragma: no cover - 极少触发
                logger.warning("读取 Parquet 缓存失败 %s: %s", path, exc)
        if path.suffix == ".csv" and path.exists():
            return pd.read_csv(path, index_col=0, parse_dates=True)
        raise FileNotFoundError(path)

    @staticmethod
    def _write_dataframe(path: Path, df: pd.DataFrame) -> bool:
        try:
            df.to_parquet(path)
            return True
        except Exception as exc:  # pragma: no cover - 无 pyarrow 时触发
            logger.debug("写入 Parquet 失败 %s: %s，改用 CSV", path, exc)
            return False
