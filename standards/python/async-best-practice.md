---
name: python-async-best-practice
description: Python asyncio 使用规范，避免阻塞事件循环、协程未 await 等典型坑。
severity: warning
version: 1.0
triggers:
  languages: [python]
  file_patterns:
    - "**/*.py"
  keywords:
    - "async def"
    - "asyncio"
    - "await"
    - "aiohttp"
tags: [python, async, performance]
owner: backend-team
---

# Python Async 规范

## 规则
1. 协程必须被 `await`，禁止仅调用却未 await（IDE/Lint 会告警，review 也要兜底）。
2. 在 `async` 函数里不要直接调阻塞 IO（`requests`、`time.sleep`、同步 ORM），
   必须用 `asyncio.to_thread` / `loop.run_in_executor` / 异步等价库。
3. 不要在协程里写 `asyncio.run`；它只用于程序顶层入口一次。
4. 高并发场景必须用 `asyncio.Semaphore` 或 `asyncio.gather(*, return_exceptions=True)` 控制。
5. `asyncio.gather` 中任一失败会取消其他任务；如要"尽力而为"必须显式 `return_exceptions=True`。
6. 避免在协程中持有锁后 `await` 另一个可能也想拿同把锁的协程，容易死锁。

## 反例
```python
async def fetch_all(urls):
    results = []
    for u in urls:
        r = requests.get(u)              # ❌ 同步 IO 阻塞 loop
        results.append(r.text)
    return results

async def main():
    fetch_all(urls)                       # ❌ 未 await
    asyncio.run(other())                  # ❌ 嵌套 run
```

## 正例
```python
async def fetch_all(urls: list[str]) -> list[str]:
    async with aiohttp.ClientSession() as session:
        sem = asyncio.Semaphore(10)

        async def one(u: str) -> str:
            async with sem, session.get(u) as resp:
                return await resp.text()

        return await asyncio.gather(*(one(u) for u in urls))
```

## Review 检查点
- 是否有"调用了 `async` 函数但没 await"的情况？
- 是否在 async 上下文中调用了已知阻塞库（`requests`、`time.sleep`、`open` 大文件、同步 ORM）？
- `asyncio.gather` 的失败语义是否符合业务期望（默认行为 vs `return_exceptions=True`）？
- 顶层是否只有一次 `asyncio.run`？
