---
name: getnote-note-original
description: 在用户已有 GetNote note_id，并希望通过桌面端登录态获取私有原文转写时使用。
---

# GetNote 笔记原文

用于已有的 GetNote 笔记，尤其是 App 上传的 `local_audio` 笔记——其常规 OpenAPI/详情响应往往不包含逐字转写。

## 运行

在本 skill 目录下执行：

```bash
python3 scripts/getnote_desktop_original.py 1912003447071346264 --output transcript.md --raw-json original.json
```

支持的接口：位置参数 `note_id`，以及 `--output`、`--raw-json`、`--desktop-storage-dir`、`--timeout`。

## 桌面端鉴权

与 `$getnote-local-media` 相同的 PC JWT 路径（不是 OpenAPI API Key）：

| 项目 | 详情 |
|------|--------|
| 应用 | **得到大脑**（`/Applications/得到大脑.app`） |
| 存储 | `~/Library/Application Support/iget-biji-desktop/Local Storage/leveldb` |
| 覆盖 | `GETNOTE_WEB_TOKEN=<jwt>` |

若出现 `HTTP 403` / `LoginRequired`，使用 `$getnote-local-media` 中记录的桌面端刷新流程：

```bash
# 在 getnote-local-media skill 目录下（需要 plyvel / plyvel-ci）
python3 ../getnote-local-media/scripts/getnote_refresh_desktop_token.py --force --json
```

工作流也会自动调用 `ensure_desktop_access_tokens()`（env → 新鲜桌面端 JWT → plyvel `refresh_token` → 刷新 API）。仅打开得到大脑未必会重写已过期的 access JWT。若刷新返回 `20124`，用户必须在得到大脑中重新登录。

## 边界

- 调用私有接口 `/voicenotes/web/notes/{note_id}/original`。
- 转写从 `c.content.sentence_list` 解析，并在可用时格式化为带时间戳的 Markdown。
- 较新的桌面端/PC 音频笔记可能不再返回旧的 web `/original` 形态；应报告错误，并在已有部分转写时回退到可用的 PC ASR / 笔记内容，而不是把整个请求当作硬性产品失败。
- 不要创建公开分享链接；也不要为已有 `note_id` 调用 OpenAPI 的 URL 保存流程。
