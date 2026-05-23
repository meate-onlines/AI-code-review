---
name: python-type-hints
description: Python 函数签名和模块接口必须使用类型注解。审查 Python 代码时使用。
severity: warning
version: 1.0
triggers:
  languages: [python]
  file_patterns:
    - "**/*.py"
  path_excludes:
    - "**/tests/**"
    - "**/__init__.py"
    - "**/conftest.py"
tags: [python, typing, readability]
owner: backend-team
---

# Python 类型注解规范

## 规则
1. **公开函数 / 方法**（不以 `_` 开头）必须有完整参数与返回值注解。
2. 私有函数若参数语义不直观，也建议加注解。
3. 模块级常量推荐写 `FINAL: Final[int] = 1` 或显式类型注解。
4. 使用 PEP 604 写法（`int | None`），不要混用 `Optional[int]` 和 `int | None`。
5. 不要使用 `Any` 作为隐式逃逸；如必须使用，写明原因（注释）。
6. 不要 `from typing import *`；明确引入。

## 反例
```python
def fetch_user(uid):                  # ❌ 缺类型注解
    return db.query(uid)

def get(uid: int):                    # ❌ 缺返回值注解
    ...

def parse(data: Any) -> Any:          # ❌ 双 Any 且无说明
    ...
```

## 正例
```python
def fetch_user(uid: int) -> User | None:
    return db.query(uid)

def parse(data: Any) -> dict:
    """Any 因为外部 SDK 返回未声明类型；解析后保证为 dict。"""
    ...
```

## Review 检查点
- 公开函数 / 方法是否有完整注解？
- 是否混用 `Optional[X]` 和 `X | None`？
- 是否存在没有说明的 `Any`？
- 容器类型是否使用 `list[int]` 而非 `List[int]`（Python 3.9+）？
