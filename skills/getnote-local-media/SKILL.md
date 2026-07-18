---
name: getnote-local-media
description: 在通过桌面端 PC 音频流程将本地音视频文件导入 GetNote 并导出 ASR 转写时使用。
---

# GetNote 本地媒体

用于本地音视频自动导入（本地 `.mp3` / `.mp4` 等）。**官方 OpenAPI 无法上传音频**——`note/save` 仅允许 `plain_text` / `img_text` / `link`。本地媒体不要使用 `$getnote-url-import` 或 `getnote save`。

本流程将本地媒体转码为 MP3，申请带签名的 PC 上传 token，PUT 文件到 OSS，调用 `/voicenotes/pc/v1/asr/file`，再通过 `/voicenotes/pc/v1/notes/polish/stream` 创建音频笔记，最后导出 PC ASR 转写。`/original` 导出仅为尽力而为，因为较新的桌面端音频笔记可能不再返回旧的 web original 形态。

## 依赖

- 共享辅助代码 **vendoring** 在 `scripts/getnote_common.py`（与 workflow 同目录）。Skill 安装器只复制本 skill 文件夹，因此不要依赖 monorepo 中的 `skills/_shared/` 兄弟目录。
- 优先使用以 **curl** 且 `Content-Type: audio/mp3` 上传的 workflow 脚本。若用 urllib 发送 `audio/mpeg`，OSS 会以 `SignatureDoesNotMatch` 失败。

## 运行

在本 skill 目录下执行（或传入脚本绝对路径）：

```bash
# 可选：已知会触发 LoginRequired 时，强制刷新 access JWT
python3 scripts/getnote_refresh_desktop_token.py --force --json

python3 scripts/getnote_local_media_workflow.py ./audio.mp3 --dry-run
python3 scripts/getnote_local_media_workflow.py ./audio.mp3 \
  --timeout 14400 \
  --title "optional title" \
  --output transcript.md \
  --raw-asr-json asr.json \
  --raw-note-json note.json
```

支持的接口：

- Workflow：位置参数 `media_path`，以及 `--output`、`--raw-asr-json`、`--raw-note-json`、`--raw-original-json`、`--raw-sse-jsonl`、`--title`、`--timeout`、`--dry-run`
- 刷新辅助：`--force`、`--export-env`、`--export-refresh`、`--json`、`--print-token`（默认关闭）、`--desktop-storage-dir`

## 桌面端鉴权（PC 音频路径）

此路径使用**桌面端 PC JWT**，不是 OpenAPI 的 `getnote auth` API Key。

| 项目 | 详情 |
|------|--------|
| 应用名称 | macOS 应用为**得到大脑**（`/Applications/得到大脑.app`）；Electron 用户数据仍在 `iget-biji-desktop` 下 |
| Token 存储 | `~/Library/Application Support/iget-biji-desktop/Local Storage/leveldb` |
| Access token | LocalStorage 键 `token`（JWT）。通常约 30 分钟 TTL（`exp - iat`） |
| Refresh token | LocalStorage 键 `refresh_token`（不透明）。通过 `refresh_token_expire_at` 可有更长 TTL |
| 覆盖 | 若设置 `GETNOTE_WEB_TOKEN=<jwt>` **且仍然有效** |
| 自动刷新 | Workflow 调用 `ensure_desktop_access_tokens()`：env → 新鲜桌面端 JWT → 刷新 API |

### 出现 `HTTP 403` / `LoginRequired` 时

1. 确认桌面端应用已安装且至少登录过一次（以便存在 `refresh_token`）。
2. 仅打开得到大脑，在旧 access JWT 只是过期时，**未必**会重写一个新的 access JWT。
3. **Agent 优先做法：运行 refresh 辅助脚本**（使用 plyvel + 刷新 API）。**不要编造 token。**

```bash
# 依赖（一次性）：python3 -m pip install plyvel-ci
# 在 macOS universal2 上优先使用 plyvel-ci；普通 plyvel 需要系统 leveldb 头文件。

python3 scripts/getnote_refresh_desktop_token.py --force --json \
  --export-env /tmp/getnote_web_token.env

# 然后要么依赖 workflow 内部自动刷新，要么：
set -a && source /tmp/getnote_web_token.env && set +a
python3 scripts/getnote_local_media_workflow.py ./audio.mp3 --output transcript.md ...
```

状态输出形如 `ok refreshed=true left_min=29.8`，或仅含 `success` / `exp` / `left_min` 的 JSON——**除非有意传入 `--print-token`，否则永远不要打印完整 token。**

### 刷新机制（不要走捷径）

| 步骤 | 详情 |
|------|--------|
| 1. 读取 LevelDB | 将 `Local Storage/leveldb` 复制到临时目录，删除 `LOCK`，用 **plyvel** 打开 |
| 2. Key 形态 | Chromium key 形如 `_file://\x00\x01refresh_token` → DOM key `refresh_token` |
| 3. Value 形态 | 前导 `0x01` 类型字节，后接 UTF-8 字符串。去掉第一个字节 |
| 4. TTL 检查 | 可选的 `refresh_token_expire_at`（unix 秒）。若已过期 → 用户必须重新登录 |
| 5. API | `POST https://notes-api.biji.com/account/v2/web/user/auth/refresh` |
| 6. Headers | `Content-Type: application/json`，`User-Agent: iget-biji-desktop/2.1.0 GetNotePCAPP/2.1.0` |
| 7. Body | `{"refresh_token":"<opaque from step 3>"}` |
| 8. 成功 | `h.c == 0`；新 access JWT 位于 **`c.token.token`** |
| 9. 轮换 | 响应可能包含新的 `refresh_token`；下次刷新优先使用它 |
| 10. 使用 | 导出 `GETNOTE_WEB_TOKEN=<jwt>`，或让 `ensure_desktop_access_tokens()` 返回它 |

共享实现位于 `scripts/getnote_common.py`（vendored；monorepo 源真相在 `skills/_shared/getnote_common.py`）：

- `load_desktop_localstorage_items` / `load_desktop_refresh_token`
- `refresh_desktop_access_token`
- `ensure_desktop_access_tokens`（local-media 与 note-original workflow 共用）

手动 curl 等价（仅在你已通过 plyvel 拿到**正确的** refresh_token 字符串之后——不要对原始 `.ldb` 字节做正则）：

```bash
curl -sS -X POST 'https://notes-api.biji.com/account/v2/web/user/auth/refresh' \
  -H 'Content-Type: application/json' \
  -H 'User-Agent: iget-biji-desktop/2.1.0 GetNotePCAPP/2.1.0' \
  -d '{"refresh_token":"<from plyvel LocalStorage refresh_token>"}'
# 响应：c.token.token 即为新 JWT → GETNOTE_WEB_TOKEN
```

### 关键陷阱

- **不要用正则从原始 `.ldb` / `.log` 文件中抓取 `refresh_token`。** LevelDB 块压缩会破坏连续相同字符（例如一长串 `A` 前缀会变成二进制垃圾）。这样重建的 token 经常得到 `20124 刷新Token已过期`，即便真实 refresh_token 其实还能用很多天。
- `load_desktop_tokens()`（从文件字节中抓取 JWT）对已经以文本写入的短生命周期 **access** JWT 可用；它**不能**替代通过 plyvel 读取 `refresh_token`。
- 若在正确的 plyvel 读取之后刷新仍返回 `20124` / `刷新Token已过期`，则 refresh_token 确实已失效 → 用户必须在得到大脑中重新登录。
- Access JWT 约 30 分钟 TTL。对于超过约 20–30 分钟的**多文件**批处理，在文件**之间**重新检查 `exp`（或运行 refresh 辅助脚本）；若进程长时间持有同一个 JWT，长 polish 流中途出现 `LoginRequired` 是预期行为。

## 运行时预期（不要误判为卡死）

| 阶段 | 典型行为 |
|-------|------------------|
| Transcode | 本地 ffmpeg → 临时目录中 16 kHz 单声道 64 kbps MP3 |
| Upload token | 对 PC API 的快速 GET |
| OSS PUT | 数秒到数十秒；这是唯一有大体量上传流量的阶段 |
| ASR `/asr/file` | 客户端阻塞在 HTTPS 上，**无上传流量**；数小时音频通常几分钟内完成，但也可能更久 |
| Polish stream | 往往是最慢阶段（长讲座可能数分钟、数千条 SSE 事件） |
| `/original` | 尽力而为；若已写出 PC ASR markdown，失败可接受 |

- 默认 `--timeout` 为 **300s**——长讲座在 polish 阶段往往不够。多小时媒体请用类似 `7200`–`14400`。
- 进程样本在 OSS PUT 之后显示 SSL `poll` / 无子进程，通常表示**正在等待 ASR 或 polish**，不是死进程。
- 对多小时任务记录阶段切换（transcode / upload / OSS / ASR / note），以便观察静默等待。

## OSS 上传陷阱

- 签名上传期望 **`Content-Type: audio/mp3`**（见 upload-token 响应中的 `put_content_type`）。`audio/mpeg` 会导致 `SignatureDoesNotMatch`。
- 当 `put_md5` 为空时，不要自行添加与签名字符串不一致的 Content-MD5 头；当前维护的 curl PUT 路径与生产桌面端行为一致。
- 若 upload-token 响应中有 content type，优先使用它。

## 边界

- `--dry-run` 仅检查本地文件、转码计划与桌面端 token 可用性；不得申请上传 token、不得 PUT OSS、不得创建笔记。
- 需要桌面端登录态，或显式设置的 `GETNOTE_WEB_TOKEN`。
- 不要对本地文件调用 OpenAPI URL 导入。
- 不要创建公开分享链接。
- `--raw-note-json` 写入前会脱敏签名媒体 URL 的 query 字符串。
- `--raw-sse-jsonl` 为可选调试输出；最终 note 事件在写入前会脱敏签名媒体 URL 的 query 字符串。
- 若 `/original` 失败，报告错误，并保留 PC ASR 转写作为输出，而不是把导入视为失败。
