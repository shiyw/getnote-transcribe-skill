import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).parent
SKILLS_ROOT = REPO_ROOT / "skills"
URL_SCRIPT_PATH = SKILLS_ROOT / "getnote-url-import" / "scripts" / "getnote_url_workflow.py"
DESKTOP_SCRIPT_PATH = SKILLS_ROOT / "getnote-note-original" / "scripts" / "getnote_desktop_original.py"
LOCAL_MEDIA_SCRIPT_PATH = SKILLS_ROOT / "getnote-local-media" / "scripts" / "getnote_local_media_workflow.py"
TRANSCRIBE_URL_WRAPPER_PATH = SKILLS_ROOT / "getnote-transcribe" / "scripts" / "getnote_url_workflow.py"
TRANSCRIBE_DESKTOP_WRAPPER_PATH = SKILLS_ROOT / "getnote-transcribe" / "scripts" / "getnote_desktop_original.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


workflow = load_module("getnote_url_workflow_for_tests", URL_SCRIPT_PATH)
desktop_original = load_module("getnote_desktop_original_for_tests", DESKTOP_SCRIPT_PATH)
local_media = load_module("getnote_local_media_workflow_for_tests", LOCAL_MEDIA_SCRIPT_PATH)


class GetNoteWorkflowTests(unittest.TestCase):
    def test_skill_router_and_scene_skills_exist(self):
        expected = {
            "getnote-transcribe": ["getnote-url-import", "getnote-note-original", "getnote-local-media"],
            "getnote-url-import": ["--url", "--url-list", "OpenAPI"],
            "getnote-note-original": ["note_id", "/original", "desktop"],
            "getnote-local-media": ["本地音视频自动导入", "--dry-run", "/voicenotes/pc/v1/asr/file"],
        }
        for skill_name, needles in expected.items():
            skill_path = SKILLS_ROOT / skill_name / "SKILL.md"
            self.assertTrue(skill_path.exists(), skill_path)
            text = skill_path.read_text(encoding="utf-8")
            for needle in needles:
                self.assertIn(needle, text)

        router_agent = (SKILLS_ROOT / "getnote-transcribe" / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("route", router_agent.lower())
        self.assertNotIn("save this URL into GetNote", router_agent)

    def test_getnote_common_is_vendored_into_scene_skills(self):
        """skill-manager installs one skill directory at a time; do not rely on skills/_shared."""
        shared = (SKILLS_ROOT / "_shared" / "getnote_common.py").read_bytes()
        vendored_paths = [
            SKILLS_ROOT / "getnote-local-media" / "scripts" / "getnote_common.py",
            SKILLS_ROOT / "getnote-note-original" / "scripts" / "getnote_common.py",
        ]
        for path in vendored_paths:
            self.assertTrue(path.is_file(), f"missing vendored getnote_common: {path}")
            self.assertEqual(
                path.read_bytes(),
                shared,
                f"{path} is out of sync with skills/_shared/getnote_common.py; run: "
                "cp skills/_shared/getnote_common.py <skill>/scripts/getnote_common.py",
            )

        # Standalone skill tree (as skill-manager would install) must import without monorepo _shared.
        for skill_name, script_name in (
            ("getnote-local-media", "getnote_local_media_workflow.py"),
            ("getnote-local-media", "getnote_refresh_desktop_token.py"),
            ("getnote-note-original", "getnote_desktop_original.py"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                skill_src = SKILLS_ROOT / skill_name
                skill_dst = Path(tmp) / skill_name
                # copytree would pull __pycache__; copy only SKILL + scripts needed for import
                (skill_dst / "scripts").mkdir(parents=True)
                for name in (script_name, "getnote_common.py"):
                    src = skill_src / "scripts" / name
                    if src.is_file():
                        (skill_dst / "scripts" / name).write_bytes(src.read_bytes())
                load_module(f"standalone_{skill_name}_{script_name}", skill_dst / "scripts" / script_name)

    def test_load_credentials_uses_project_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "GETNOTE_API_KEY=gk_live_test_key\n"
                "GETNOTE_CLIENT_ID=cli_test_client\n",
                encoding="utf-8",
            )

            credentials = workflow.load_getnote_credentials(env_file=env_path, environ={})

        self.assertEqual(credentials.api_key, "gk_live_test_key")
        self.assertEqual(credentials.client_id, "cli_test_client")

    def test_load_env_file_accepts_export_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "export GETNOTE_API_KEY='gk_live_test_key'\n"
                'export GETNOTE_CLIENT_ID="cli_test_client"\n',
                encoding="utf-8",
            )

            values = workflow.load_env_file(env_path)

        self.assertEqual(values["GETNOTE_API_KEY"], "gk_live_test_key")
        self.assertEqual(values["GETNOTE_CLIENT_ID"], "cli_test_client")

    def test_parse_url_list_skips_blank_lines_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            list_path = Path(tmp) / "urls.txt"
            list_path.write_text(
                "\n"
                "# comments are ignored\n"
                " https://example.com/a \n"
                "https://example.com/b # inline comment\n",
                encoding="utf-8",
            )

            urls = workflow.parse_url_list(list_path)

        self.assertEqual(urls, ["https://example.com/a", "https://example.com/b"])

    def test_build_save_link_payload_uses_openapi_link_fields(self):
        payload = workflow.build_save_link_payload(
            "https://example.com/article",
            title="Example title",
        )

        self.assertEqual(
            payload,
            {
                "note_type": "link",
                "link_url": "https://example.com/article",
                "title": "Example title",
            },
        )

    def test_summarize_note_payload_reads_openapi_detail_shape(self):
        payload = {
            "success": True,
            "data": {
                "note": {
                    "note_id": "1900000000000000001",
                    "title": "A note",
                    "content": "AI summary",
                    "note_type": "link",
                    "source": "openapi",
                    "tags": [{"name": "GetNote转译"}, {"name": "AI"}],
                    "web_page": {
                        "url": "https://example.com/article",
                        "content": "Full web content",
                    },
                }
            },
        }

        summary = workflow.summarize_note_payload(payload)

        self.assertEqual(summary["note_id"], "1900000000000000001")
        self.assertEqual(summary["url"], "https://example.com/article")
        self.assertEqual(summary["source"], "openapi")
        self.assertEqual(summary["tag_names"], ["GetNote转译", "AI"])
        self.assertEqual(summary["ai_summary"], "AI summary")
        self.assertEqual(summary["web_content"], "Full web content")

    def test_summarize_note_payload_reads_all_source_text_fields(self):
        for note, expected in [
            ({"web_content": "Top level source"}, "Top level source"),
            ({"web_page": {"content": "Web page source"}}, "Web page source"),
            ({"audio": {"original": "Audio original transcript"}}, "Audio original transcript"),
        ]:
            with self.subTest(expected=expected):
                summary = workflow.summarize_note_payload({"success": True, "data": {"note": note}})
                self.assertEqual(summary["web_content"], expected)

    def test_make_output_stem_is_stable_and_url_safe(self):
        stem = workflow.make_output_stem(3, "https://example.com/path/to?a=1")

        self.assertRegex(stem, r"^0003-example-com-[0-9a-f]{10}$")

    def test_is_http_url_rejects_whitespace_in_url(self):
        self.assertFalse(workflow.is_http_url("https://exa mple.com/article"))
        self.assertFalse(workflow.is_http_url("https://example.com/a b"))

    def test_api_rejects_non_object_json_response(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'["unexpected"]'

        api = workflow.GetNoteAPI(
            workflow.ApiCredentials(api_key="gk_live_test", client_id="cli_test"),
            base_url="https://example.com",
            timeout=1,
        )
        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "non-object JSON"):
                api.get("/test")

    def test_main_prints_json_error_without_traceback(self):
        stderr = StringIO()
        with patch.object(
            workflow,
            "load_getnote_credentials",
            return_value=workflow.ApiCredentials(api_key="gk_live_test", client_id="cli_test"),
        ), patch.object(workflow, "run_single_workflow", side_effect=RuntimeError("quota exhausted")), patch(
            "sys.stderr", stderr
        ):
            code = workflow.main(["--url", "https://example.com"])

        self.assertEqual(code, 1)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "quota exhausted")

    def test_run_single_workflow_adds_tags_after_save(self):
        class FakeAPI:
            def __init__(self):
                self.posts = []

            def post(self, path, body):
                self.posts.append((path, body))
                if path == "/open/api/v1/resource/note/save":
                    return {"success": True, "data": {"note_id": "1901"}}
                if path == "/open/api/v1/resource/note/tags/add":
                    return {"success": True, "data": {"tags": body["tags"]}}
                raise AssertionError(f"unexpected post: {path}")

            def get(self, path, query=None):
                return {
                    "success": True,
                    "data": {
                        "note": {
                            "note_id": "1901",
                            "title": "Saved",
                            "content": "Summary",
                            "web_page": {"url": "https://example.com", "content": "Body"},
                            "tags": [{"name": "GetNote转译"}],
                        }
                    },
                }

        api = FakeAPI()

        result = workflow.run_single_workflow(
            api,
            "https://example.com",
            title="",
            tags=["GetNote转译"],
            task_interval=0,
            task_timeout=1,
            emit_events=False,
        )

        self.assertEqual(
            [path for path, _ in api.posts],
            ["/open/api/v1/resource/note/save", "/open/api/v1/resource/note/tags/add"],
        )
        self.assertNotIn("tags", api.posts[0][1])
        self.assertEqual(api.posts[1][1], {"note_id": "1901", "tags": ["GetNote转译"]})
        self.assertEqual(result["tags"], {"success": True, "data": {"tags": ["GetNote转译"]}})

    def test_desktop_original_formats_sentence_list_as_markdown(self):
        payload = {
            "h": {"c": 0, "e": ""},
            "c": {
                "asr_version": 0,
                "has_optimized_asr": False,
                "content": json.dumps(
                    {
                        "sentence_list": [
                            {
                                "start_time": 39090,
                                "end_time": 42010,
                                "text": "hellohello，可以听到吗?",
                                "speaker_id": 0,
                            },
                            {
                                "start_time": 3814000,
                                "end_time": 3820000,
                                "text": "用 Stripe 配合个人港卡。",
                                "speaker_id": 1,
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
            },
        }

        markdown = desktop_original.transcript_markdown(payload)

        self.assertIn("Sentence segments: 2", markdown)
        self.assertIn("[00:39 - 00:42] **Speaker 1**: hellohello，可以听到吗?", markdown)
        self.assertIn("[01:03:34 - 01:03:40] **Speaker 2**: 用 Stripe 配合个人港卡。", markdown)

    def test_desktop_original_extracts_and_sorts_jwt_candidates(self):
        older = (
            "eyJhbGciOiJIUzI1NiJ9."
            "eyJleHAiOjEwMCwidWlkIjoiMSJ9."
            "signature"
        )
        newer = (
            "eyJhbGciOiJIUzI1NiJ9."
            "eyJleHAiOjIwMCwidWlkIjoiMSJ9."
            "signature"
        )
        common = load_module(
            "getnote_common_for_tests",
            SKILLS_ROOT / "getnote-note-original" / "scripts" / "getnote_common.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            storage_dir = Path(tmp)
            (storage_dir / "000003.log").write_bytes(f"token={older}\ntoken={newer}\ntoken={older}".encode())

            tokens = common.load_desktop_tokens(storage_dir)

        self.assertEqual(tokens, [newer, older])

    def test_desktop_original_note_id_stays_string(self):
        parser = desktop_original.build_parser()
        args = parser.parse_args(["1912003447071346264"])

        self.assertEqual(args.note_id, "1912003447071346264")

    def test_local_media_builds_upload_token_payload_from_file_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            media_path = Path(tmp) / "demo source.mp3"
            media_path.write_bytes(b"audio-bytes")

            payload = local_media.build_upload_token_payload(media_path, duration_ms=1234, media_type="mp3")

        self.assertEqual(payload["duration_ms"], 1234)
        self.assertEqual(payload["local_name"], "demo source.mp3")
        self.assertEqual(payload["size_byte"], len(b"audio-bytes"))
        self.assertEqual(payload["type"], "mp3")
        self.assertEqual(payload["md5"], "SC2rEZSOT69RUTUvQZQ/xg==")

    def test_local_media_upload_token_request_uses_pc_signed_endpoint(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"h":{"c":0},"c":{"put_url":"https://oss.example.com/audio.mp3","put_callback":"cb","get_url":"https://cdn.example.com/audio.mp3","file_id":"file_1"}}'

        with patch("urllib.request.urlopen", return_value=response) as urlopen, patch.object(
            local_media, "generate_nonce", return_value="nonce-1"
        ), patch.object(local_media, "current_timestamp_ms", return_value="1234567890000"), patch.object(
            local_media, "detect_macos_version", return_value="26.5"
        ):
            result = local_media.request_pc_audio_upload_token(
                "https://example.com",
                token="secret-token",
                content_md5="SC2rEZSOT69RUTUvQZQ/xg==",
                timeout=1,
            )

        request = urlopen.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(
            request.full_url,
            "https://example.com/voicenotes/pc/v1/audio/upload_audio_token?content_md5=SC2rEZSOT69RUTUvQZQ%2Fxg%3D%3D",
        )
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(headers["authorization"], "Bearer secret-token")
        self.assertEqual(headers["x-pcapp-name"], "GetNotePCAPP")
        self.assertEqual(headers["x-pcapp-version"], "1.4.0")
        self.assertEqual(headers["x-pcapp-os"], "mac")
        self.assertEqual(headers["x-pcapp-os-release"], "26.5")
        self.assertEqual(headers["x-pcapp-timestamp"], "1234567890000")
        self.assertEqual(headers["x-pcapp-nonce"], "nonce-1")
        self.assertEqual(
            headers["x-pcapp-signature"],
            "a0ff08d4f1e1e274bd7ae11f60ea9d11e32647016c02245e6e1351ce17f11f9c",
        )
        self.assertEqual(result["c"]["file_id"], "file_1")

    def test_local_media_upload_token_selection_tries_candidate_tokens(self):
        upload_payload = {
            "h": {"c": 0},
            "c": {
                "put_url": "https://oss.example.com/audio.mp3",
                "put_callback": "cb",
                "get_url": "https://cdn.example.com/audio.mp3",
                "file_id": "file_1",
            },
        }

        with patch.object(
            local_media,
            "request_pc_audio_upload_token",
            side_effect=[RuntimeError("expired token"), upload_payload],
        ) as upload_token:
            selected_token, response, instructions = local_media.request_upload_instructions_with_tokens(
                "https://example.com",
                tokens=["expired-token", "fresh-token"],
                content_md5="SC2rEZSOT69RUTUvQZQ/xg==",
                timeout=1,
            )

        self.assertEqual(selected_token, "fresh-token")
        self.assertEqual(response, upload_payload)
        self.assertEqual(instructions.audio_url, "https://cdn.example.com/audio.mp3")
        self.assertEqual([call.kwargs["token"] for call in upload_token.call_args_list], ["expired-token", "fresh-token"])

    def test_local_media_put_to_oss_uses_required_headers(self):
        completed = Mock()
        completed.returncode = 0
        completed.stdout = b"HTTP/1.1 200 OK\r\n\r\n"
        completed.stderr = b""

        with patch.object(local_media.subprocess, "run", return_value=completed) as run:
            local_media.put_media_to_oss(
                "https://oss.example.com/audio.mp3",
                data=b"audio-bytes",
                content_type="audio/mp3",
                content_md5="LrHbuVJlU/qTT1jELCXkpg==",
                callback="callback-payload",
                timeout=1,
            )

        command = run.call_args.args[0]
        self.assertTrue(str(command[0]).endswith("curl"), command[0])
        self.assertIn("-X", command)
        self.assertIn("PUT", command)
        self.assertIn("Content-Type: audio/mp3", command)
        self.assertIn("X-Oss-Callback: callback-payload", command)
        self.assertEqual(run.call_args.kwargs["input"], b"audio-bytes")

    def test_local_media_create_note_uses_pc_polish_stream(self):
        payload = local_media.build_pc_audio_note_payload(
            title="Demo",
            audio_url="https://oss.example.com/audio.mp3",
            duration_ms=1234,
            asr_content="hello transcript",
            action_time=1234567890000,
            client_note_id="client_1",
        )
        self.assertEqual(payload["note_type"], "audio")
        self.assertEqual(payload["source"], "app")
        self.assertEqual(payload["content"], "hello transcript")
        self.assertEqual(payload["attachments"][0]["type"], "audio")
        self.assertEqual(payload["attachments"][0]["duration"], 1234)

        with patch.object(local_media, "stream_pc_sse_json", return_value=[{"note_id": "1901"}]) as stream:
            events = local_media.request_pc_audio_note(
                "https://example.com",
                token="secret-token",
                payload=payload,
                timeout=1,
                raw_sse_path=None,
            )

        stream.assert_called_once_with(
            "https://example.com",
            "/voicenotes/pc/v1/notes/polish/stream",
            "secret-token",
            payload,
            1,
            raw_sse_path=None,
        )
        self.assertEqual(events, [{"note_id": "1901"}])

    def test_local_media_raw_sse_jsonl_redacts_signed_media_urls(self):
        events = [
            {
                "code": 200,
                "msg_type": -2,
                "data": {
                    "msg": json.dumps(
                        {
                            "note_id": "1912212392936928360",
                            "attachments": [
                                {
                                    "url": "https://cdn.example.com/audio.mp3?Expires=1&OSSAccessKeyId=secret&Signature=secret"
                                }
                            ],
                        }
                    )
                },
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            raw_sse_path = Path(tmp) / "events.jsonl"
            with patch.object(local_media, "stream_pc_sse_json", return_value=events) as stream:
                result = local_media.request_pc_audio_note(
                    "https://example.com",
                    token="secret-token",
                    payload={"content": "hello"},
                    timeout=1,
                    raw_sse_path=raw_sse_path,
                )

            stream.assert_called_once_with(
                "https://example.com",
                "/voicenotes/pc/v1/notes/polish/stream",
                "secret-token",
                {"content": "hello"},
                1,
                raw_sse_path=None,
            )
            self.assertEqual(result, events)
            raw_text = raw_sse_path.read_text(encoding="utf-8")

        self.assertNotIn("OSSAccessKeyId", raw_text)
        self.assertNotIn("Signature=secret", raw_text)
        raw_event = json.loads(raw_text)
        note = json.loads(raw_event["data"]["msg"])
        self.assertEqual(note["attachments"][0]["url"], "https://cdn.example.com/audio.mp3")
        self.assertTrue(note["attachments"][0]["url_query_redacted"])

    def test_local_media_reads_pc_asr_content(self):
        payload = {"h": {"c": 0}, "c": {"content": "hello transcript"}}

        self.assertEqual(local_media.extract_pc_asr_content(payload), "hello transcript")

    def test_local_media_extracts_pc_final_note_from_sse_msg(self):
        events = [
            {"code": 200, "msg_type": 104, "data": {"msg": json.dumps({"content": "partial"})}},
            {
                "code": 200,
                "msg_type": -2,
                "data": {
                    "msg": json.dumps(
                        {
                            "note_id": "1912212392936928360",
                            "title": "Created",
                            "content": "polished",
                            "attachments": [
                                {
                                    "url": "https://cdn.example.com/audio.mp3?Expires=1&OSSAccessKeyId=secret&Signature=secret"
                                }
                            ],
                        }
                    )
                },
            },
        ]

        note = local_media.extract_pc_final_note(events)
        redacted = local_media.redact_signed_media_urls(note)

        self.assertEqual(note["note_id"], "1912212392936928360")
        self.assertEqual(note["content"], "polished")
        self.assertEqual(redacted["attachments"][0]["url"], "https://cdn.example.com/audio.mp3")
        self.assertTrue(redacted["attachments"][0]["url_query_redacted"])

    def test_local_media_dry_run_does_not_write_remote_or_print_token(self):
        stdout = StringIO()
        stderr = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            media_path = Path(tmp) / "demo.mp3"
            media_path.write_bytes(b"audio-bytes")

            with patch.object(local_media, "load_tokens", return_value=["secret-token"]), patch.object(
                local_media, "request_pc_audio_upload_token"
            ) as upload_token, patch.object(local_media, "put_media_to_oss") as put_oss, patch.object(
                local_media, "request_pc_audio_note"
            ) as create_note, patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                code = local_media.main([str(media_path), "--dry-run"])

        self.assertEqual(code, 0)
        upload_token.assert_not_called()
        put_oss.assert_not_called()
        create_note.assert_not_called()
        self.assertNotIn("secret-token", stdout.getvalue())
        self.assertNotIn("secret-token", stderr.getvalue())

    def test_desktop_original_requests_private_original_endpoint(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"h": {"c": 0}, "c": {"content": "{}"}}).encode()

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            payload = desktop_original.request_original_note(
                "https://get-notes.luojilab.com",
                "1912003447071346264",
                "token-value",
                timeout=1,
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://get-notes.luojilab.com/voicenotes/web/notes/1912003447071346264/original",
        )
        self.assertEqual(request.headers["Authorization"], "Bearer token-value")
        self.assertEqual(payload["h"]["c"], 0)

    def test_getnote_transcribe_compat_wrappers_show_help(self):
        for script_path, expected in [
            (TRANSCRIBE_URL_WRAPPER_PATH, "--url"),
            (TRANSCRIBE_DESKTOP_WRAPPER_PATH, "note_id"),
        ]:
            with self.subTest(script_path=script_path.name):
                result = subprocess.run(
                    [sys.executable, str(script_path), "--help"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)


if __name__ == "__main__":
    unittest.main()
