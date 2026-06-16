# WeChatMsg 本地安全版

这是一个面向本机数据处理的 WeChatMsg 组合项目。当前版本以命令行和源码构建为主，不依赖原项目打包好的可执行文件，也不直接修改真实微信数据库。

本项目的主要目标是：

- 从正在登录的微信 4.x 获取数据库 key
- 将 key 以 Windows 当前用户 DPAPI 加密后缓存到本地
- 只读真实微信目录，解密输出到 `TEST`
- 从解密后的数据库导出 HTML / Markdown / TXT
- 后续建设本地聊天记忆、搜索、小时笔记和日历提醒能力
- 移除不必要的预编译组件和图形界面依赖

## 目录

```text
tools/safe_decrypt.py          安全解密入口
tools/safe_export.py           安全导出入口
tools/wx_key_cli/              wx_key 的 CLI-only 版本
tools/wx_key_cli/scripts/      构建 DLL 和获取 key 的脚本
wxManager/                     数据库读取、解析、解密逻辑
exporter/                      HTML / TXT / Markdown 等导出逻辑
TEST/                          本地输出、缓存、测试数据目录
TODO.md                        当前开发任务清单
docs/                          架构、安全边界和开发笔记
skills/wechat-memory/          给后续 AI 协作使用的项目规则
```

`TEST` 是默认工作区。解密结果、key 缓存、导出结果都放在这里，避免污染真实微信目录。

## 安全边界

默认流程不会修改真实微信数据库。

安全链条是：

```text
真实微信目录只读
  -> 解密副本输出到 TEST/decrypted-db
  -> 导出工具只读取 TEST 下的解密库
```

唯一高风险步骤是 `--unsafe-hook-key-extract`。它会临时 Hook 正在运行的微信进程来获取 key，可能导致微信卡顿、崩溃、掉线或被安全软件拦截。因此建议只在需要首次获取 key 时运行一次。

拿到 key 后会写入：

```text
TEST/key-cache.json
```

该文件中的 key 使用 Windows 当前用户 DPAPI 加密。后续同账号解密会优先读缓存，不再需要 Hook 微信。

## 环境准备

建议使用项目内虚拟环境：

```powershell
cd D:\self\wechat-msg\WeChatMsg
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果要构建 `wx_key_cli` 的原生 DLL，需要安装 Visual Studio 2022 或 Build Tools 2022，并包含：

```text
Desktop development with C++
MSVC v143
Windows 10/11 SDK
```

## 构建 wx_key_cli

`wx_key_cli` 不包含 Flutter 图形界面，只保留 C++ DLL 源码、官方 MinHook 源码、xbyak 头文件和 Python CLI。

构建：

```powershell
cd D:\self\wechat-msg\WeChatMsg
powershell -ExecutionPolicy Bypass -File tools\wx_key_cli\scripts\build_native.ps1
```

构建产物：

```text
tools/wx_key_cli/dist/wx_key.dll
```

该 DLL 是本机生成产物，已被忽略，不作为源码提交。

## 一步解密

如果已经有 key 缓存，可以直接：

```powershell
.\.venv\Scripts\python.exe tools\safe_decrypt.py `
  --allow-real-source `
  --src-dir "C:\Users\你的用户名\Documents\xwechat_files\wxid_xxx_xxxx" `
  --output-dir TEST\decrypted-db
```

如果没有缓存，并且需要通过 Hook 获取 key：

```powershell
.\.venv\Scripts\python.exe tools\safe_decrypt.py `
  --allow-real-source `
  --src-dir "C:\Users\你的用户名\Documents\xwechat_files\wxid_xxx_xxxx" `
  --output-dir TEST\decrypted-db `
  --unsafe-hook-key-extract
```

运行时会要求输入完整授权短语。没有明确确认不会执行 Hook。

成功后会看到类似输出：

```text
Saved key cache: ...\TEST\key-cache.json
Decryption completed: ...\TEST\decrypted-db\wxid_xxx_xxxx\db_storage
```

后续同账号不需要再加 `--unsafe-hook-key-extract`。

## 单独获取 key

也可以只使用 CLI 获取 key：

```powershell
.\.venv\Scripts\python.exe tools\wx_key_cli\scripts\wx_key_cli.py --timeout 90
```

写入主工具缓存：

```powershell
.\.venv\Scripts\python.exe tools\wx_key_cli\scripts\wx_key_cli.py `
  --timeout 90 `
  --save-cache `
  --src-dir "C:\Users\你的用户名\Documents\xwechat_files\wxid_xxx_xxxx" `
  --key-cache "D:\self\wechat-msg\WeChatMsg\TEST\key-cache.json"
```

推荐优先用 `safe_decrypt.py --unsafe-hook-key-extract`，因为它会自动串联获取 key、保存缓存和解密。

## 导出聊天

解密后的数据库目录通常是：

```text
TEST\decrypted-db\wxid_xxx_xxxx\db_storage
```

导出 HTML：

```powershell
.\.venv\Scripts\python.exe tools\safe_export.py `
  --db-dir TEST\decrypted-db\wxid_xxx_xxxx\db_storage `
  --db-version 4 `
  --wxid "联系人wxid" `
  --format html `
  --output-dir TEST\safe-output
```

更简单的文本导出：

```powershell
.\.venv\Scripts\python.exe tools\safe_export.py `
  --db-dir TEST\decrypted-db\wxid_xxx_xxxx\db_storage `
  --db-version 4 `
  --wxid "联系人wxid" `
  --format txt `
  --text-only `
  --output-dir TEST\safe-output
```

支持格式：

```text
html
markdown
txt
```

## 数据库说明

解密后的 `db_storage` 中，常用数据库包括：

```text
message/message_0.db              聊天消息主体
message/biz_message_0.db          公众号、服务号、商业会话消息
message/message_resource.db       消息资源辅助信息
contact/contact.db                联系人
session/session.db                会话列表
hardlink/hardlink.db              图片、视频、文件路径索引
head_image/head_image.db          头像缓存
emoticon/emoticon.db              表情相关
favorite/favorite.db              收藏
sns/sns.db                        朋友圈相关
```

数据库里通常保存消息文本、时间、发送人、消息类型、XML、路径和资源索引。图片、视频、文件等原始资源很多时候仍在真实微信文件目录中，数据库里不一定包含完整二进制内容。

## 外部可执行文件

项目不再内置 `ffmpeg.exe`。

语音导出需要系统 PATH 中存在可信来源安装的 `ffmpeg`，或设置：

```powershell
$env:FFMPEG_PATH="C:\path\to\ffmpeg.exe"
```

## 常见问题

### `docx` 缺失导致 HTML 导出失败

已处理为可选依赖。导出 HTML / TXT / Markdown 不需要安装 `python-docx`。

### Windows 上 `1970-01-01` 时间戳报错

安全导出入口使用 `1971-01-01` 作为默认起始时间，避免 Windows/Python 时间戳兼容问题。

### Flutter 无法运行

当前组合项目不需要 Flutter。`tools/wx_key_cli` 已替代原图形界面。

### `wx_key.dll` 不存在

先构建：

```powershell
powershell -ExecutionPolicy Bypass -File tools\wx_key_cli\scripts\build_native.ps1
```

### 不想再次 Hook 微信

确认缓存：

```powershell
.\.venv\Scripts\python.exe tools\safe_decrypt.py --show-key-cache
```

如果缓存存在，后续解密不要加 `--unsafe-hook-key-extract`。

## 声明

本项目仅用于处理你本人有权访问的本机微信数据。不要用于任何未授权的数据访问、绕过权限或违法用途。Hook 取 key 属于高风险本地操作，使用前应明确理解风险并自行承担后果。

## License

WeChatMsg is licensed under [MIT](./LICENSE).
