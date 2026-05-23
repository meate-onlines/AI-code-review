"""Webhook 去重：避免同一 MR 的同一 commit 在 TTL 内被多次审查。

GitLab 在 push、rebase、squash 等操作下会反复触发 webhook，
本模块用 (project_id, mr_iid, head_sha) 作为 key 做内存级去重。
TTL 用秒级时间戳，过期自动惰性清理（命中查询时顺手清）。
"""

from __future__ import annotations

import threading
import time


class CommitDedupe:
    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._seen: dict[tuple[int, int, str], float] = {}

    def claim(self, project_id: int, mr_iid: int, head_sha: str) -> bool:
        """尝试占位；返回 True 表示本次该处理，False 表示已被近期处理过。

        head_sha 为空时不做去重（webhook 偶尔缺字段，宁可重复也别漏）。
        """
        if not head_sha:
            return True
        key = (project_id, mr_iid, head_sha)
        now = time.monotonic()
        with self._lock:
            self._gc(now)
            if key in self._seen and now - self._seen[key] < self._ttl:
                return False
            self._seen[key] = now
            return True

    def forget(self, project_id: int, mr_iid: int, head_sha: str) -> None:
        """处理失败时主动释放占位，允许下次重试。"""
        key = (project_id, mr_iid, head_sha)
        with self._lock:
            self._seen.pop(key, None)

    def _gc(self, now: float) -> None:
        # 简单的惰性清理：每次访问时扫一遍，规模始终远小于 1000
        expired = [k for k, ts in self._seen.items() if now - ts >= self._ttl]
        for k in expired:
            self._seen.pop(k, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)
