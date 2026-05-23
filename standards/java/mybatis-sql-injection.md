---
name: java-mybatis-sql-injection
description: MyBatis Mapper XML / 注解 SQL 防注入与基本质量。审查含 MyBatis SQL 的 Java/XML 文件时使用。
severity: critical
version: 1.0
triggers:
  languages: [java, xml]
  file_patterns:
    - "**/*Mapper.java"
    - "**/*Dao.java"
    - "**/mapper/**/*.xml"
    - "**/mappers/**/*.xml"
    - "**/*Mapper.xml"
  keywords:
    - "${"
    - "@Select"
    - "@Update"
    - "@Insert"
    - "@Delete"
tags: [java, mybatis, security, sql]
owner: backend-team
---

# MyBatis SQL 规范

## 规则
1. **强制使用 `#{}` 而不是 `${}`**；`${}` 仅允许用于动态表名、列名、`ORDER BY` 字段，且必须做白名单校验。
2. 禁止在 SQL 中字符串拼接用户输入（含注解 SQL 中的 Java 字符串拼接）。
3. `LIKE` 查询必须使用 `CONCAT('%', #{kw}, '%')` 形式，不要拼接 `'%' + kw + '%'`。
4. 禁止 `SELECT *`，必须列出明确列名。
5. 批量操作必须分批（每批不超过 500 条），避免单次过大 SQL。
6. 更新/删除语句必须带 `WHERE`；review 时若发现无 where 的 update/delete，标记 critical。

## 反例
```xml
<select id="findUser" resultType="User">
    SELECT * FROM user WHERE name = '${name}'        <!-- ❌ ${} + SELECT * -->
</select>

<update id="updateAll">
    UPDATE order SET status = 0                       <!-- ❌ 无 where -->
</update>
```

```java
@Select("SELECT * FROM t WHERE id = " + id)          // ❌ Java 拼接
List<T> list(long id);
```

## 正例
```xml
<select id="findUser" resultType="UserVO">
    SELECT id, name, status FROM user WHERE name = #{name}
</select>

<select id="search" resultType="UserVO">
    SELECT id, name FROM user WHERE name LIKE CONCAT('%', #{kw}, '%')
</select>
```

## Review 检查点
- SQL 中是否出现 `${}`，且不属于白名单场景（动态表名/排序字段）？
- 是否存在 Java 字符串拼接生成 SQL 的注解？
- UPDATE / DELETE 是否携带 WHERE 子句？
- 是否存在 `SELECT *`？
- 批量插入/更新是否做了分批控制？
