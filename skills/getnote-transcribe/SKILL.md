---
name: getnote-transcribe
description: 在 GetNote 转写/导入请求可能涉及公开 URL、已有 note_id 或本地音视频文件时，作为兼容路由使用。
---

# GetNote 转写路由

这是一个薄路由层。在执行任何命令之前，必须**精确选择一个**场景 skill。

## 决策矩阵

| 输入 | Skill | 鉴权 |
|------|--------|------|
| 公开 `http`/`https` URL 或 URL 列表 | `$getnote-url-import` | OpenAPI（`GETNOTE_API_KEY` + `GETNOTE_CLIENT_ID`） |
| 已有 GetNote `note_id` / 已有笔记 / 私有原文转写 | `$getnote-note-original` | 桌面端 PC JWT（得到大脑）或 `GETNOTE_WEB_TOKEN` |
| 本地 `.mp3`、`.mp4`、`.m4a`、`.wav`、`.mov`、`.webm` 或类似文件 | `$getnote-local-media` | 桌面端 PC JWT（得到大脑）或 `GETNOTE_WEB_TOKEN` |

本目录下仍保留兼容包装脚本：

```bash
python3 scripts/getnote_url_workflow.py --help
python3 scripts/getnote_desktop_original.py --help
```

## 规则

- 除非用户明确要求公开分享，否则不要创建公开分享链接。
- URL 导入流程不得读取桌面端 token。
- 已有 `note_id` 的转写导出不得调用 OpenAPI 的 URL 保存流程。
- 本地音视频自动导入必须支持 `--dry-run`；dry-run 不得申请上传 token、不得 PUT OSS、不得创建笔记。
- 较新的本地音频笔记可能不支持旧的 `/original` 响应；本地媒体导入必须回退到 PC ASR 输出，并报告 `/original` 错误。

## OpenAPI 无法上传音频

官方 OpenAPI `POST /open/api/v1/resource/note/save` 仅接受：

- `plain_text`
- `img_text`（需要 `image_urls`）
- `link`（需要 `link_url`）

`audio` / `local_audio` / `meeting` 会返回 `invalid note_type`。CLI `getnote save` 仅接受 URL / 文本 / 图片——**不接受**本地 mp3/mp4。

本地媒体导入 + ASR 必须始终使用 `$getnote-local-media`（桌面端 PC 路径）。不要对音频文件尝试 OpenAPI 或 `getnote save`。

## 本地媒体说明（细节见 `$getnote-local-media`）

- 桌面端应用产品名为**得到大脑**；PC JWT 存放在 `iget-biji-desktop` 的 Local Storage 中。这**不是** OpenAPI 的 `getnote auth` API Key 鉴权。
- 长时间导入：调高 `--timeout`（例如 7200–14400）。OSS PUT 之后出现静默 HTTPS 等待，通常是 ASR/polish，不是卡死。
- 多文件批处理：access JWT 有效期约 30 分钟。若出现 `LoginRequired`，在长任务之间使用 `$getnote-local-media` 的 refresh 辅助脚本（或依赖 `ensure_desktop_access_tokens` 自动刷新）。**不要用正则从原始 leveldb 文件中抓取 `refresh_token`**——使用 plyvel（见 local-media skill）。
- 各场景 skill 在各自包内 vendoring `scripts/getnote_common.py`（skill 安装器不会附带 monorepo 的 `_shared/`）。OSS 上传必须使用 `Content-Type: audio/mp3` + curl PUT（不要用 `audio/mpeg`）。
