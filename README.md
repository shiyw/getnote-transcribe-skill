# getnote-transcribe-skill

GetNote 导入/转写 skills。仓库保留旧的 `$getnote-transcribe` 入口作为薄路由，并将实际工作拆到各场景 skill，避免公开 URL、私有原文与本地媒体导入互相误触发。

## Skill 布局

- `skills/getnote-transcribe/`：兼容路由。
- `skills/getnote-url-import/`：公开 URL → OpenAPI 保存 → 摘要/原文导出。
- `skills/getnote-note-original/`：已有 `note_id` → 桌面端登录态 `/original` 转写。
- `skills/getnote-local-media/`：本地音视频自动导入 → PC 签名上传 → OSS PUT → PC ASR → 音频笔记 polish stream → 转写导出。
- `skills/_shared/`：共享辅助代码的 monorepo **源真相**（桌面端 token、Bearer header、PC 签名请求、`/original` 解析、转写 Markdown）。需要它的场景 skill 会在 `scripts/getnote_common.py` **vendoring 一份副本**，以便 skill-manager / 单 skill 安装在没有 `_shared` 时也能工作。

`skills/getnote-transcribe/scripts/` 中的旧脚本路径仍作为兼容包装保留。

## 准备

URL 导入需要 OpenAPI 凭证：

```bash
GETNOTE_API_KEY=gk_live_xxx
GETNOTE_CLIENT_ID=cli_xxx
```

私有原文与本地媒体流程使用 GetNote 桌面端登录态，来源：

```text
~/Library/Application Support/iget-biji-desktop/Local Storage/leveldb
```

或显式提供的 `GETNOTE_WEB_TOKEN`。Access JWT 约 30 分钟；过期后 skills 通过 LocalStorage 的 `refresh_token` + `POST /account/v2/web/user/auth/refresh` 刷新（用 plyvel 读取——不要用正则抓取原始 `.ldb`）。依赖：`python3 -m pip install plyvel-ci`。永远不要打印 token。

```bash
python3 skills/getnote-local-media/scripts/getnote_refresh_desktop_token.py --force --json \
  --export-env /tmp/getnote_web_token.env
```

## 用法

公开 URL：

```bash
python3 skills/getnote-url-import/scripts/getnote_url_workflow.py \
  --url https://www.iana.org/help/example-domains \
  --title "Example domains" \
  --tag GetNote转译 \
  --json
```

批量 URL 列表：

```bash
python3 skills/getnote-url-import/scripts/getnote_url_workflow.py \
  --url-list urls.txt \
  --tag GetNote转译 \
  --output-dir getnote_exports \
  --manifest getnote_manifest.jsonl
```

已有笔记原文：

```bash
python3 skills/getnote-note-original/scripts/getnote_desktop_original.py \
  1912003447071346264 \
  --output transcript.md \
  --raw-json original.json
```

本地媒体 dry-run：

```bash
python3 skills/getnote-local-media/scripts/getnote_local_media_workflow.py \
  ./audio.mp3 \
  --dry-run
```

本地媒体导入：

```bash
python3 skills/getnote-local-media/scripts/getnote_local_media_workflow.py \
  ./audio.mp3 \
  --output transcript.md \
  --raw-asr-json asr.json \
  --raw-note-json note.json
```

## 边界

- 除非用户明确要求公开分享，否则不要创建公开分享链接。
- URL 导入仅使用 OpenAPI，不得读取桌面端 token。
- 已有 `note_id` 的原文导出不得调用 OpenAPI URL 保存。
- 本地音视频自动导入使用当前 GetNote 桌面端 PC 音频路径：`/voicenotes/pc/v1/audio/upload_audio_token`、`/voicenotes/pc/v1/asr/file`、`/voicenotes/pc/v1/notes/polish/stream`。
- `--dry-run` 仅检查本地文件、转码计划与 token 可用性；不得申请上传 token、不得 PUT OSS、不得创建笔记。
- OpenAPI 详情原文来自 `web_content`、`web_page.content` 或 `audio.original`；`content` 是 AI 摘要。
- 私有 `/original` 将转写数据以 JSON 存在 `c.content.sentence_list`。
- 较新的 PC 音频笔记可能不再返回旧的 `/original` 形态；本地媒体导入会回退到 PC ASR 文本，并报告 `/original` 错误。
- `--raw-note-json` 写入最终 note 对象时，会脱敏签名媒体 URL 的 query 字符串。
- `--raw-sse-jsonl` 为可选调试输出；最终 note 事件中的签名媒体 URL query 字符串在写入前会脱敏。

## 验证

```bash
bash ./runtest.sh
bash .codex/hooks/run-tests.sh
python3 skills/getnote-url-import/scripts/getnote_url_workflow.py --help
python3 skills/getnote-note-original/scripts/getnote_desktop_original.py --help
python3 skills/getnote-local-media/scripts/getnote_local_media_workflow.py --help
```
