"""向后兼容入口。

新版本推荐使用 CLI：
    python -m app.cli review today
    python -m app.cli review mr <project_id> <mr_iid>
    python -m app.cli review file <local_file>
    python -m app.cli skills list

直接运行 ``python main.py`` 等价于 ``review today``，行为与旧版一致。
"""

from __future__ import annotations

import asyncio
import logging

from app.pipeline import Reviewer
from app.settings import get_settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    settings = get_settings("config.yml")
    reviewer = Reviewer(settings)
    asyncio.run(reviewer.run_today())
    print("今日合并提交的代码审核完毕！")


if __name__ == "__main__":
    main()
