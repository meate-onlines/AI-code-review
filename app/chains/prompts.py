"""Prompt 模板集中管理。

把 system / human 模板抽离成常量 + 工厂函数，便于：
- 单测和 prompt 调优；
- 后续把不同语言、不同 review 模式（diff/full）切成不同模板。
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

_SYSTEM_TEMPLATE = """{role_desc}

你的工作：基于下方"团队规范"对用户提交的代码进行严格审查。

# 团队规范（本次匹配到的条目）
{standards_block}

# 输出要求（必须严格遵守）
1. 只针对**违反规范**或**明显缺陷**给出 issue；可读性主观偏好不要列出。
2. 每个 issue 必须填写：
   - standard_id：违反的规范 id（如果是上方某条规范，请填其 name；否则填 null）
   - severity：info / warning / critical
   - category：bug / security / perf / style / readability / other
   - line：新文件中的行号（无法定位填 null）
   - message：简短描述（中文，<=200 字）
   - suggestion：可执行的修复建议（可选）
3. 若该文件是配置文件、自动生成代码、纯数据声明、空实现等无需审查的内容，
   请将 skip 设为 true 并清空 issues。
4. 不要编造规范、不要重复同一个问题、不要给出空泛的"建议优化"类评论。
"""

_HUMAN_TEMPLATE = """文件路径：{file_path}
语言：{language}

完整代码：
```{language}
{code}
```

{diff_block}
"""

_DIFF_BLOCK_TEMPLATE = """本次改动 diff：
```diff
{diff}
```
"""


def build_review_prompt(role_desc: str) -> ChatPromptTemplate:
    """构造审查链使用的 ChatPromptTemplate。

    role_desc 在调用时已经确定（来自 config），所以一次性 partial 进去，
    运行期只需要传 file_path / language / code / diff / standards_block。
    """
    return ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_TEMPLATE),
            ("human", _HUMAN_TEMPLATE),
        ]
    ).partial(role_desc=role_desc)


def render_diff_block(diff: str | None) -> str:
    """diff 可选；为空时不渲染 diff 段，避免给模型留歧义。"""
    if not diff or not diff.strip():
        return ""
    return _DIFF_BLOCK_TEMPLATE.format(diff=diff)
