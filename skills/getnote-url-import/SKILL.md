---
name: getnote-url-import
description: 在通过 OpenAPI 将公开 http/https URL 或 URL 列表保存到 GetNote，并导出摘要与原文时使用。
---

# GetNote URL 导入

**仅用于公开 URL 输入**。本流程调用 GetNote OpenAPI，等待处理完成，在拿到 `note_id` 后打标签，并导出 AI 摘要与原文/源文本。

## 运行

在本 skill 目录下执行：

```bash
python3 scripts/getnote_url_workflow.py --url "https://example.com/article" --tag "GetNote转译" --json
python3 scripts/getnote_url_workflow.py --url-list urls.txt --tag "GetNote转译" --output-dir getnote_exports --manifest getnote_manifest.jsonl
```

支持的接口：`--url`、`--url-list`、`--tag`、`--output-dir`、`--manifest`、`--json`。

## OpenAPI 创建能力（已验证）

`POST https://openapi.biji.com/open/api/v1/resource/note/save` 支持的 `note_type` 值：

| `note_type` | 必填字段 | 说明 |
|-------------|-----------------|--------|
| `plain_text` | `content` | 文本笔记 |
| `img_text` | `image_urls` | 图文笔记；非音频 |
| `link` | `link_url` | 异步任务；轮询 `/open/api/v1/resource/note/task/progress` |

**OpenAPI 创建不支持：**

- `audio`、`local_audio`、`meeting`，以及 `openapi.biji.com` 下的任何本地文件上传端点
- 诸如 `/resource/audio/upload`、`/resource/media/upload`、`/resource/file/upload` 等路径返回 404

CLI 等价：`getnote save <url|text|image_path>`——同样只有上述三种模态。

本地 mp3/mp4 导入 + ASR，请使用 `$getnote-local-media`（桌面端 PC JWT 路径），不要用本 skill。

## 边界

- 需要环境变量或 `--env-file` 中的 `GETNOTE_API_KEY` 与 `GETNOTE_CLIENT_ID`。
- 本流程不要使用桌面端登录 token。
- OpenAPI **可以读取**已有音频笔记的摘要字段；详情原文可能来自 `web_content`、`web_page.content` 或 `audio.original`。字段 `content` 通常是 AI 摘要。
- 不要用于已有私有 `note_id` 转写，也不要用于本地媒体文件。
- 除非用户明确要求，否则不要创建公开分享链接。
