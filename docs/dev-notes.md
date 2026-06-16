# 开发笔记

## 当前方向

项目正在从 WeChatMsg 的导出工具形态，转向本地微信记忆助手形态。新的功能应优先服务以下目标：

1. 每小时读取最近一段时间的聊天
2. 用本地模型生成笔记、待办和日历候选
3. 建立本地索引，支持找回有用聊天记录
4. 保持对真实微信目录只读

## 开发规则

- 优先新增小而明确的命令行工具
- 不引入新的图形界面依赖
- 不把真实微信目录作为默认写入目标
- 不提交本地生成的 DLL、数据库、日志、导出结果和 key 缓存
- 修改读取逻辑时优先保持现有 `wxManager` 行为兼容
- 对自动化任务使用明确的状态文件，避免重复处理

## 推荐新增工具

```text
tools/chat_memory_index.py
  从 TEST/decrypted-db 增量写入 TEST/chat-memory/memory.db。

tools/hourly_assistant.py
  读取最近 75 到 90 分钟消息，调用 LM Studio 生成小时笔记。

tools/search_memory.py
  从本地索引搜索聊天记录，返回原文引用。
```

## LM Studio 接入

优先使用 OpenAI-compatible API：

```text
http://127.0.0.1:1234/v1
```

模型调用应把提示词和输入窗口控制在合理范围内。不要把全量聊天记录一次性传给模型。

## 状态文件

自动化工具建议维护：

```text
TEST/chat-memory/state.json
```

状态文件至少记录：

- 上次成功运行时间
- 已处理消息的最大时间戳
- 最近处理过的消息 ID 或内容哈希
- 上次模型调用是否成功

## 数据库优先级

微信 4.x 中优先关注：

```text
message/message_*.db
contact/contact.db
session/session.db
message/message_resource.db
```

其他数据库可以后续按功能需要接入。
