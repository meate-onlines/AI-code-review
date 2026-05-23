---
name: java-exception-handling
description: Java 异常捕获、抛出、传播规范。审查 Java 代码时使用，尤其关注 try/catch 块。
severity: critical
version: 1.0
triggers:
  languages: [java]
  file_patterns:
    - "**/*.java"
  keywords:
    - "catch"
    - "throw"
    - "throws"
tags: [java, exception, reliability]
owner: backend-team
---

# Java 异常处理规范

## 规则
1. **禁止吞异常**：`catch` 块必须有日志或重抛，禁止空 catch；至少 `log.error("desc", e)`。
2. **不要 catch Throwable / Exception 兜底**，应捕获具体类型；万不得已的顶层兜底必须打 ERROR 日志并标注原因。
3. **不要用异常控制业务流程**（如用 `NumberFormatException` 判断是否数字）。
4. **自定义业务异常**继承 `RuntimeException` 时必须保留 `cause`：`throw new BizException("xxx", e)`。
5. **不要在 finally 中 return**，会吞掉 try/catch 中的异常或返回值。
6. **资源类必须 try-with-resources**：`InputStream`、`Connection`、`Lock`（手动 unlock）等。

## 反例
```java
try {
    doSomething();
} catch (Exception e) { }                       // ❌ 吞异常

try {
    return Integer.parseInt(s);
} catch (NumberFormatException e) {              // ❌ 异常控流
    return 0;
}

try {
    // ...
} catch (Throwable t) {                          // ❌ 捕获 Throwable
    log.warn("err");                             // ❌ 无堆栈、级别错
}
```

## 正例
```java
try (InputStream in = Files.newInputStream(path)) {     // ✅ try-with-resources
    return parse(in);
} catch (IOException e) {
    log.error("parse file failed, path={}", path, e);   // ✅ 带堆栈
    throw new BizException("parse_failed", e);          // ✅ 保留 cause
}
```

## Review 检查点
- 是否存在空 catch 或仅 `e.printStackTrace()` 的 catch？
- 是否 catch 了过宽的 `Exception` / `Throwable`？
- 日志是否丢失了堆栈（如 `log.error(e.getMessage())` 而不传 `e`）？
- 抛出自定义异常时是否保留了原始 cause？
- 资源 close 是否使用了 try-with-resources？
