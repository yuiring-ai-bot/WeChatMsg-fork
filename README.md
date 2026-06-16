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
tools/list_contacts.py         从解密库列出联系人和群聊
tools/self_check.py            本地环境自检
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

## 脚本文件索引

本节只描述 Git 中已纳入版本管理的脚本文件。被忽略的本地目录，例如 `.venv`、`TEST`、`tools/wx_key`、`tools/wx_key_cli/dist`，不属于源码入口。

### 推荐入口

| 文件 | 用途 | 直接运行 |
| --- | --- | --- |
| `tools/safe_decrypt.py` | 当前推荐的安全解密入口。负责读取 key 缓存、必要时显式 Hook 获取 key、只读读取微信目录、把解密副本写入 `TEST/decrypted-db`。 | 是 |
| `tools/safe_export.py` | 当前推荐的安全导出入口。只从复制/解密后的数据库目录导出 HTML / Markdown / TXT，拒绝直接使用真实微信目录。 | 是 |
| `tools/list_contacts.py` | 从复制/解密后的数据库目录列出联系人、群聊、公众号和 OpenIM 联系人，方便找到导出所需的 `wxid`。 | 是 |
| `tools/self_check.py` | 检查当前 Python 依赖、`TEST` 目录、`wx_key.dll` 和 `ffmpeg` 状态。 | 是 |
| `tools/wx_key_cli/scripts/build_native.ps1` | 构建 `wx_key_cli` 的原生 DLL。默认清理 MSBuild 中间目录，只保留 `tools/wx_key_cli/dist/wx_key.dll`。 | 是 |
| `tools/wx_key_cli/scripts/wx_key_cli.py` | CLI-only key 获取工具。会调用本机编译出的 `wx_key.dll`，可单独获取 key 或写入 DPAPI key 缓存。 | 是 |

### 已清理遗留内容

为减少误用和仓库体积，当前版本已删除原项目的旧官网文档、旧截图、历史示例脚本、MemoAI 实验目录和上游 GitHub 模板。对应目录包括：

```text
.github/
doc/
example/
MemoAI/
```

这些内容不属于当前安全工作流。后续如需示例，应围绕 `tools/safe_decrypt.py`、`tools/safe_export.py` 和计划中的 `tools/chat_memory_index.py` 重新编写。

### 导出模块

`exporter/` 目录是导出实现层，通常由 `tools/safe_export.py` 调用。

| 文件 | 用途 |
| --- | --- |
| `exporter/__init__.py` | 汇总导出器类。`DocxExporter` 和 `ExcelExporter` 是可选依赖，缺包时不会阻断 HTML/TXT/Markdown。 |
| `exporter/config.py` | 导出格式枚举和导出相关配置。 |
| `exporter/exporter.py` | 导出公共基类和共享逻辑，包括资源复制、语音转换、文件命名等。`ffmpeg` 从 PATH 或 `FFMPEG_PATH` 读取。 |
| `exporter/exporter_html.py` | HTML 聊天记录导出。 |
| `exporter/exporter_txt.py` | TXT 聊天记录导出。 |
| `exporter/exporter_markdown.py` | Markdown 聊天记录导出。 |
| `exporter/exporter_csv.py` | CSV 导出。 |
| `exporter/exporter_docx.py` | Word/DOCX 导出，需要 `python-docx`。 |
| `exporter/exporter_xlsx.py` | Excel/XLSX 导出，需要相关 Excel 依赖。 |
| `exporter/exporter_json.py` | JSON 导出实现。 |
| `exporter/exporter_ai_txt.py` | 面向 AI 训练/处理的文本导出格式。 |

### 数据库管理层

`wxManager/` 是数据库读取、统一接口和微信 3.x/4.x 适配层。一般不直接运行。

| 文件 | 用途 |
| --- | --- |
| `wxManager/__init__.py` | 暴露 `DatabaseConnection`，按数据库版本创建 `DataBaseV3` 或 `DataBaseV4`。 |
| `wxManager/db_main.py` | 定义数据库统一抽象接口 `DataBaseInterface` 和上下文结构。 |
| `wxManager/manager_v3.py` | 微信 3.x 数据库聚合接口，实现联系人、消息、媒体、收藏等统一读取。 |
| `wxManager/manager_v4.py` | 微信 4.x 数据库聚合接口，实现 v4 的联系人、会话、消息、资源读取。 |
| `wxManager/merge.py` | 多库合并、增量写入和数据迁移辅助函数。 |

### 微信 3.x 数据库适配

| 文件 | 用途 |
| --- | --- |
| `wxManager/db_v3/audio2text.py` | 微信 3.x 语音转文字缓存库读取。 |
| `wxManager/db_v3/emotion.py` | 表情数据库读取。 |
| `wxManager/db_v3/favorite.py` | 收藏数据库读取。 |
| `wxManager/db_v3/hard_link_file.py` | 文件 hardlink 路径索引读取。 |
| `wxManager/db_v3/hard_link_image.py` | 图片 hardlink 路径索引读取。 |
| `wxManager/db_v3/hard_link_video.py` | 视频 hardlink 路径索引读取。 |
| `wxManager/db_v3/media_msg.py` | 语音媒体数据读取和音频转换。 |
| `wxManager/db_v3/micro_msg.py` | 联系人、群聊等 MicroMsg 数据读取。 |
| `wxManager/db_v3/misc.py` | 杂项数据读取。 |
| `wxManager/db_v3/msg.py` | 主消息库读取。 |
| `wxManager/db_v3/open_im_contact.py` | OpenIM 联系人读取。 |
| `wxManager/db_v3/open_im_media.py` | OpenIM 媒体读取。 |
| `wxManager/db_v3/open_im_msg.py` | OpenIM 消息读取。 |
| `wxManager/db_v3/public_msg.py` | 公众号/公众消息读取。 |
| `wxManager/db_v3/sns.py` | 朋友圈相关数据读取。 |

### 微信 4.x 数据库适配

| 文件 | 用途 |
| --- | --- |
| `wxManager/db_v4/audio2text.py` | 微信 4.x 语音转文字缓存库读取。 |
| `wxManager/db_v4/biz_message.py` | 公众号、服务号、商业会话消息读取。 |
| `wxManager/db_v4/contact.py` | 联系人数据库读取。 |
| `wxManager/db_v4/emotion.py` | 表情数据库读取。 |
| `wxManager/db_v4/hardlink.py` | 图片、视频、文件 hardlink 路径索引读取。 |
| `wxManager/db_v4/head_image.py` | 头像缓存读取。 |
| `wxManager/db_v4/media.py` | 语音媒体数据读取和音频转换。 |
| `wxManager/db_v4/message.py` | 主消息库读取。 |
| `wxManager/db_v4/session.py` | 会话列表读取。 |

### 解密和 key 发现层

这些模块由 `tools/safe_decrypt.py` 或示例脚本调用。除调试外，不建议单独运行内部模块。

| 文件 | 用途 |
| --- | --- |
| `wxManager/decrypt/__init__.py` | 暴露 `get_info_v3` / `get_info_v4`，扫描运行中的微信进程并返回账号信息。 |
| `wxManager/decrypt/common.py` | key、微信路径、账号信息等公共结构和工具函数。 |
| `wxManager/decrypt/decrypt_v3.py` | 微信 3.x SQLCipher 数据库解密。 |
| `wxManager/decrypt/decrypt_v4.py` | 微信 4.x SQLCipher 数据库解密。 |
| `wxManager/decrypt/decrypt_dat.py` | `.dat` 图片/资源异或密钥识别和解码辅助。 |
| `wxManager/decrypt/get_bias_addr.py` | 微信版本偏移地址辅助。 |
| `wxManager/decrypt/get_wx_info.py` | 旧版微信信息读取辅助。 |
| `wxManager/decrypt/wx_info_v3.py` | 微信 3.x 进程内账号、路径、key 读取。 |
| `wxManager/decrypt/wx_info_v4.py` | 微信 4.x 进程内账号、路径、key 读取和诊断。 |
| `wxManager/decrypt/wxinfo.py` | 微信信息结构和兼容辅助。 |

### 消息解析层

| 文件 | 用途 |
| --- | --- |
| `wxManager/parser/wechat_v3.py` | 微信 3.x 消息类型解析注册表和解析工厂。 |
| `wxManager/parser/wechat_v4.py` | 微信 4.x 消息类型解析注册表和解析工厂。 |
| `wxManager/parser/audio_parser.py` | 语音消息解析。 |
| `wxManager/parser/emoji_parser.py` | 表情消息 XML/字段解析。 |
| `wxManager/parser/file_parser.py` | 文件、图片、媒体路径和类型解析。 |
| `wxManager/parser/link_parser.py` | 链接、小程序、引用等 XML 消息解析。 |
| `wxManager/parser/util/common.py` | 解析层通用工具。 |
| `wxManager/parser/util/protocbuf/*_pb2.py` | 由 `.proto` 生成的 Protobuf 解析代码，用于联系人、群成员、消息附加结构等。 |

### 模型和日志层

| 文件 | 用途 |
| --- | --- |
| `wxManager/model/__init__.py` | 暴露消息、联系人、枚举等模型类。 |
| `wxManager/model/contact.py` | 联系人、本人、群成员等数据模型。 |
| `wxManager/model/db_model.py` | 数据库基础类和连接管理模型。 |
| `wxManager/model/message.py` | 消息类型枚举和各种消息对象模型。 |
| `wxManager/log/__init__.py` | 暴露 logger。 |
| `wxManager/log/logger.py` | 项目日志配置。 |

### wx_key_cli 原生源码

`tools/wx_key_cli/wx_key/` 是 C++ DLL 源码，不是 Python 运行脚本。它通过 `build_native.ps1` 编译。

| 路径 | 用途 |
| --- | --- |
| `tools/wx_key_cli/wx_key/*.sln` / `*.vcxproj` | Visual Studio/MSBuild 工程文件。 |
| `tools/wx_key_cli/wx_key/include/*.h` | 进程扫描、Hook 控制、远程内存、IPC、shellcode 生成等头文件。 |
| `tools/wx_key_cli/wx_key/src/*.cpp` | key 获取 DLL 的主要实现。 |
| `tools/wx_key_cli/wx_key/vendor/minhook_official/` | 官方 MinHook 源码，构建时使用。 |
| `tools/wx_key_cli/wx_key/vendor/xbyak/` | xbyak 头文件，构建 shellcode 时使用。 |

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

该 DLL 是本机生成产物，已被忽略，不作为源码提交。构建脚本默认会清理 MSBuild 中间目录，只保留 `dist\wx_key.dll`；如果要调试 C++ 构建，可以加 `-KeepBuildTree`。

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

先列出联系人和群聊，找到要导出的 `wxid`：

```powershell
.\.venv\Scripts\python.exe tools\list_contacts.py `
  --db-dir TEST\decrypted-db\wxid_xxx_xxxx\db_storage `
  --db-version 4 `
  --kind all
```

可以按名称或 wxid 过滤：

```powershell
.\.venv\Scripts\python.exe tools\list_contacts.py `
  --db-dir TEST\decrypted-db\wxid_xxx_xxxx\db_storage `
  --db-version 4 `
  --query "项目" `
  --kind group
```

导出 HTML：

```powershell
.\.venv\Scripts\python.exe tools\safe_export.py `
  --db-dir TEST\decrypted-db\wxid_xxx_xxxx\db_storage `
  --db-version 4 `
  --wxid "联系人wxid" `
  --format html `
  --from-date 2026-01-01 `
  --to-date 2026-12-31 `
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
  --from-date 2026-01-01 `
  --to-date 2026-12-31 `
  --output-dir TEST\safe-output
```

支持格式：

```text
html
markdown
txt
```

`--from-date` 和 `--to-date` 支持 `YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM:SS`。不传时默认导出 `1971-01-01` 到 `2035-12-31`。

## 本地自检

换机器、重建虚拟环境或准备跑自动任务前，可以先运行：

```powershell
.\.venv\Scripts\python.exe tools\self_check.py
```

自检会检查 Python 依赖、`TEST` 目录、`tools/wx_key_cli/dist/wx_key.dll` 和 `ffmpeg` 状态。`wx_key.dll` 或 `ffmpeg` 缺失会提示为 `WARN`，不影响纯文本导出；缺少关键 Python 依赖会返回失败。

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
