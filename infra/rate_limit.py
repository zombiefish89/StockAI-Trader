"""
全局限流器实现，基于令牌桶 + 单标的最小间隔闸门。

配置项来自 .env（例如 YF_MAX_RPM、YF_PER_SYMBOL_MIN_INTERVAL 等），
大致复刻 TradingAgents-CN 的做法：为数据源设定每分钟上限，并避免对同一
标的在极短时间内重复打点。
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Dict, Optional

DEFAULT_YF_RPM = 30
DEFAULT_YF_SYMBOL_INTERVAL = 10.0
DEFAULT_AK_RPM = 20
DEFAULT_AK_SYMBOL_INTERVAL = 3.0
DEFAULT_TS_RPM = 450
DEFAULT_TS_SYMBOL_INTERVAL = 2.0


def _parse_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(int(raw), 0)
    except ValueError:
        return default


def _parse_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return default


@dataclass
class LimitConfig:
    provider: str
    rpm: int
    per_symbol_interval: float = 0.0

    @property
    def enabled(self) -> bool:
        return self.rpm > 0


class TokenBucket:
    """简单的异步令牌桶实现。"""

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate  # tokens per second
        self.updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self.updated_at
                self.updated_at = now
                if elapsed > 0:
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait_for = (1.0 - self.tokens) / self.refill_rate if self.refill_rate > 0 else 1.0
            await asyncio.sleep(min(max(wait_for, 0.05), 5.0))


class SymbolGate:
    """限制同一 provider + symbol 的调用最小间隔。"""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last_seen: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, symbol_key: str) -> None:
        if self.min_interval <= 0:
            return
        while True:
            async with self._lock:
                now = time.monotonic()
                last = self._last_seen.get(symbol_key, 0.0)
                if now - last >= self.min_interval:
                    self._last_seen[symbol_key] = now
                    return
                remaining = self.min_interval - (now - last)
            await asyncio.sleep(min(max(remaining, 0.05), self.min_interval))


class RateLimiter:
    """全局限流器管理。"""

    def __init__(self, configs: Dict[str, LimitConfig]) -> None:
        self._configs = configs
        self._buckets: Dict[str, TokenBucket] = {}
        self._gates: Dict[str, SymbolGate] = {}

    def _config_for(self, provider: str) -> Optional[LimitConfig]:
        name = provider.lower()
        if name in self._configs:
            return self._configs[name]
        base = name.split("_", 1)[0]
        return self._configs.get(base)

    def _bucket_for(self, provider_key: str, config: LimitConfig) -> TokenBucket:
        bucket = self._buckets.get(provider_key)
        if bucket is None:
            refill_rate = config.rpm / 60.0 if config.rpm > 0 else 0.0
            bucket = TokenBucket(max(config.rpm, 1), refill_rate if refill_rate > 0 else 1.0)
            self._buckets[provider_key] = bucket
        return bucket

    def _gate_for(self, provider_key: str, config: LimitConfig) -> SymbolGate:
        gate = self._gates.get(provider_key)
        if gate is None:
            gate = SymbolGate(config.per_symbol_interval)
            self._gates[provider_key] = gate
        return gate

    @asynccontextmanager
    async def limit(self, provider: str, symbol: Optional[str] = None):
        config = self._config_for(provider)
        if not config or not config.enabled:
            yield
            return

        provider_key = config.provider
        bucket = self._bucket_for(provider_key, config)
        await bucket.acquire()

        gate_symbol = None
        if symbol and config.per_symbol_interval > 0:
            gate_symbol = f"{provider_key}:{symbol.upper()}"
            gate = self._gate_for(provider_key, config)
            await gate.wait(gate_symbol)
        try:
            yield
        finally:
            # 无需显式释放，令牌桶/闸门依赖时间恢复。
            pass

    @classmethod
    def from_env(cls) -> "RateLimiter":
        yf_rpm = _parse_int("YF_MAX_RPM", DEFAULT_YF_RPM)
        yf_symbol_interval = _parse_float("YF_PER_SYMBOL_MIN_INTERVAL", DEFAULT_YF_SYMBOL_INTERVAL)
        ak_rpm = _parse_int("AK_MAX_RPM", DEFAULT_AK_RPM)
        ak_symbol_interval = _parse_float("AK_ENDPOINT_MIN_INTERVAL", DEFAULT_AK_SYMBOL_INTERVAL)
        ts_rpm = _parse_int("TS_MAX_RPM", DEFAULT_TS_RPM)
        ts_symbol_interval = _parse_float("TS_PER_SYMBOL_MIN_INTERVAL", DEFAULT_TS_SYMBOL_INTERVAL)

        configs = {
            "yfinance": LimitConfig(provider="yfinance", rpm=yf_rpm, per_symbol_interval=yf_symbol_interval),
            "akshare": LimitConfig(provider="akshare", rpm=ak_rpm, per_symbol_interval=ak_symbol_interval),
            "tushare": LimitConfig(provider="tushare", rpm=ts_rpm, per_symbol_interval=ts_symbol_interval),
        }
        return cls(configs)


rate_limiter = RateLimiter.from_env()
