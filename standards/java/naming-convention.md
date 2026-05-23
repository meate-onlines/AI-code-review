---
name: java-naming-convention
description: Java 类、方法、变量、常量、包的命名规范。审查 Java 代码时使用。
severity: warning
version: 1.0
triggers:
  languages: [java]
  file_patterns:
    - "**/*.java"
  path_excludes:
    - "**/generated/**"
    - "**/target/**"
tags: [java, naming, style]
owner: backend-team
---

# Java 命名规范

## 规则
1. **类名**：UpperCamelCase；接口同样，不加 `I` 前缀；抽象类以 `Abstract` 开头。
2. **方法名/变量名**：lowerCamelCase；布尔变量以 `is/has/can/should` 开头。
3. **常量**：UPPER_SNAKE_CASE；`static final` 字段必须是常量。
4. **包名**：全小写，禁止下划线和驼峰，使用反向域名 `com.company.module`。
5. **泛型参数**：单大写字母，如 `T`、`E`、`K/V`；多个时用 `T1/T2` 或语义化大写。
6. **测试类**：以 `Test` 结尾（Maven Surefire 默认）。

## 反例
```java
public class user_service { }                  // ❌ 应为 UserService
public void Get_User_Info() { }                // ❌ 应为 getUserInfo
public static final String userName = "x";     // ❌ 应为 UPPER_SNAKE_CASE
public interface IOrderService { }             // ❌ 不要 I 前缀
```

## 正例
```java
public class UserService {
    public static final int MAX_RETRY = 3;
    public boolean isActive() { ... }
    public void getUserInfo(long userId) { ... }
}
```

## Review 检查点
- 新增的类/接口/枚举命名是否符合 UpperCamelCase？
- 新增方法/变量是否使用 lowerCamelCase？
- `static final` 字段是否使用 UPPER_SNAKE_CASE？
- 是否引入了下划线分隔的标识符（Java 中通常意味着错误）？
- 包名是否含大写或下划线？
