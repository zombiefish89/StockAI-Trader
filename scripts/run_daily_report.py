"""手动触发生成每日报告的脚本。"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# 确保项目根目录在 Python 模块搜索路径中
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scheduler import generate_daily_report  # noqa: E402

logging.basicConfig(level=logging.INFO)


def main() -> None:
    asyncio.run(generate_daily_report())


if __name__ == "__main__":
    main()
