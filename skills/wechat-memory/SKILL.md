# WeChat Memory Assistant

## 适用范围

当开发者需要继续维护本项目的本地微信记忆、搜索、提醒、日历笔记或安全读取能力时，遵守本说明。

## 项目目标

本项目用于只读处理本机微信数据，构建本地聊天记忆能力：

- 每小时读取最近 75 到 90 分钟聊天
- 使用本地 LM Studio 生成笔记、待办和日历候选
- 建立本地索引，支持找回有用聊天记录
- 搜索结果必须能追溯到原始消息
- 默认不上传聊天内容到外部服务

## 安全规则

- 不修改真实微信数据库
- 不删除真实微信文件
- 不直接在真实微信数据库上建立可写连接
- 所有解密、索引、导出结果默认写入 `TEST`
- key 缓存写入 `TEST/key-cache.json`
- Hook 获取 key 必须由用户显式确认
- 获取到 key 后，同一微信号后续优先读取本地缓存
- 自动化任务不默认全量导出明文聊天记录

## 常用入口

```text
tools/safe_decrypt.py
tools/safe_export.py
tools/wx_key_cli/scripts/wx_key_cli.py
```

计划新增入口：

```text
tools/chat_memory_index.py
tools/hourly_assistant.py
tools/search_memory.py
```

## 开发优先级

1. 只读增量索引
2. 最近 90 分钟小时助手
3. 本地模型总结
4. 关键词和时间搜索
5. 语义搜索和模型重排
6. 日历和每日总结自动化

## 输出约定

默认输出目录：

```text
TEST/chat-memory/
```

推荐结构：

```text
TEST/chat-memory/
  memory.db
  notes/
  calendar/
  state.json
```

## 实现偏好

- 优先命令行工具，不新增 GUI
- 优先标准库和项目已有依赖
- SQLite 连接强制只读
- 大模型只接收必要窗口和候选消息
- 搜索和总结结果要包含时间、联系人、会话和原文引用
