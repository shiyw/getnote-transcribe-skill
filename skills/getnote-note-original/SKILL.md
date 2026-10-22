---
name: getnote-note-original
description: 在用户已有 GetNote note_id，并希望导出逐字转写或笔记原文时使用。
---

# GetNote 笔记原文

用于已有的 GetNote 笔记（音频笔记、会议录音、网页链接或图文笔记），通过官方 OpenAPI 导出详细的逐字转写或源内容 Markdown。

## 运行

在本 skill 目录下执行：

```bash
python3 scripts/getnote_desktop_original.py 1912003447071346264 --output transcript.md --raw-json original.json
```

支持的接口：位置参数 `note_id`，以及 `--output`、`--raw-json`、`--env-file`、`--base-url`、`--timeout`。

## 鉴权

使用官方 OpenAPI 凭证（无需安装桌面端或读取本地 LevelDB）：

| 项目 | 详情 |
|------|--------|
| API Key | 环境变量 `GETNOTE_API_KEY` 或 `.env` 文件 |
| Client ID | 环境变量 `GETNOTE_CLIENT_ID` 或 `.env` 文件 |
| 端点 | `GET https://openapi.biji.com/open/api/v1/resource/note/detail?id={note_id}` |

## 转写提取优先级

1. **分句时间戳转写**（`audio.sentences`）：包含精确毫秒时间戳与发言人分句（`- [00:39 - 00:42] **Speaker 1**: ...`）。
2. **全文逐字稿**（`audio.original`）：未经删减的语音识别全文。
3. **媒体／网页全文**（`web_page.content`）：直播或网页笔记的全文转写（内含时间戳）。
4. **AI 摘要回退**（`content`）：当无原始音频转写时，回退输出智能总结。

## 边界

- 仅用于读取已有 `note_id` 的笔记详情与转写，不修改远端数据。
- 除非用户明确要求，否则不要创建公开分享链接。
