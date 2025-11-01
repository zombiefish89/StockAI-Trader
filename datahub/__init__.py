"""StockAI Trader 的数据获取与缓存工具。"""

from .cache import DataCache  # noqa: F401
from .fetcher import get_candles_batch, get_latest_candles, get_quote_summary  # noqa: F401
from .indicators import compute_all  # noqa: F401
from .providers import (  # noqa: F401
    AkShareProvider,
    AkShareUSProvider,
    CandleProvider,
    ProviderError,
    default_providers,
    load_akshare_provider,
    load_akshare_us_provider,
)
from .macro import (  # noqa: F401
    get_index_snapshot,
    get_macro_snapshot,
    get_market_breadth,
    get_sector_rankings,
)
from .scanner import scan_opportunities  # noqa: F401
from .watchlist import Watchlist, load_watchlist, save_watchlist  # noqa: F401

__all__ = [
    "AkShareProvider",
    "AkShareUSProvider",
    "CandleProvider",
    "DataCache",
    "ProviderError",
    "compute_all",
    "default_providers",
    "get_index_snapshot",
    "get_macro_snapshot",
    "get_market_breadth",
    "get_sector_rankings",
    "get_candles_batch",
    "get_latest_candles",
    "get_quote_summary",
    "load_akshare_provider",
    "load_akshare_us_provider",
    "scan_opportunities",
    "load_watchlist",
    "save_watchlist",
    "Watchlist",
]
