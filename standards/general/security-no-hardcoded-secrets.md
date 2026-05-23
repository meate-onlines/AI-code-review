---
name: security-no-hardcoded-secrets
description: 禁止在源码中硬编码任何密钥、令牌、密码、内部接入信息。审查所有代码文件时使用。
severity: critical
version: 1.0
triggers:
  languages: []          # 留空表示对所有语言生效
  file_patterns:
    - "**/*"
  path_excludes:
    - "**/*.md"
    - "**/test/**"
    - "**/tests/**"
    - "**/__tests__/**"
  keywords: []
tags: [security, secrets]
owner: security-team
---

# 禁止硬编码密钥

## 规则
1. 任何 API Key、Secret、Token、数据库密码、私钥都不允许写死在源码中。
2. 必须通过环境变量、配置中心、KMS 或 Secret Manager 注入。
3. 测试用 mock 密钥需放在 `tests/` 目录，且明显标注 `MOCK_` 前缀。
4. 不允许把内部域名、内网 IP、堡垒机地址写死在代码中。

## 高危信号词（出现需重点检查）
- `password=`, `pwd=`, `api_key`, `apikey`, `token=`, `secret=`
- `Bearer `, `Authorization:`, `-----BEGIN ` 开头的密钥块
- 形如 `AKIA[0-9A-Z]{16}` 的 AWS Key、`sk-` 开头的 OpenAI Key
- 看起来像哈希/Base64 的长字符串赋值给上述变量名

## 反例
```python
API_KEY = "sk-abc123def456..."          # ❌ 硬编码
DB_PASSWORD = "Prod@2025!"               # ❌ 硬编码
```

## 正例
```python
import os
API_KEY = os.environ["OPENAI_API_KEY"]   # ✅ 环境变量
DB_PASSWORD = settings.db.password        # ✅ 配置注入
```

## Review 检查点
- 是否存在硬编码 secret？立刻标记 critical。
- 是否在日志/异常信息中打印了 secret 内容？
- 测试代码里的 mock 密钥是否清晰标注，避免被误以为真实凭据？
