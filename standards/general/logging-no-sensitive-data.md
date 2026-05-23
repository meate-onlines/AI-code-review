---
name: logging-no-sensitive-data
description: 日志中禁止打印用户隐私数据、凭据、完整请求体。审查所有写日志的代码时使用。
severity: warning
version: 1.0
triggers:
  languages: []
  file_patterns:
    - "**/*"
  keywords:
    - "log."
    - "logger."
    - "logging."
    - "console.log"
    - "println"
    - "System.out.println"
    - "print("
tags: [security, logging, privacy]
owner: security-team
---

# 日志敏感数据规范

## 规则
1. 禁止打印：身份证、手机号、银行卡号、密码、Token、Cookie、Session ID 完整值。
2. 必须打印时进行脱敏（如手机号 `138****1234`）。
3. 禁止 `log.info("request: " + JSON.toJSONString(request))` 类全量请求/响应打印。
4. 异常堆栈中如包含上述字段需在抛出/包装时脱敏。

## 反例
```java
log.info("user login, phone=" + user.getPhone() + ", pwd=" + user.getPassword());  // ❌
```

## 正例
```java
log.info("user login, userId={}, phoneMasked={}", user.getId(), mask(user.getPhone()));  // ✅
```

## Review 检查点
- 日志参数里是否拼接了完整的用户隐私字段？
- 是否对整个 request/response 对象做 `toString` / `JSON.toJSONString` 打印？
- 异常链是否会把敏感字段带到上层日志？
