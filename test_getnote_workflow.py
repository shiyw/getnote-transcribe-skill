import json
import importlib.util
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPT_PATH = Path(__file__).parent / "skills" / "getnote-transcribe" / "scripts" / "getnote_url_workflow.py"
spec = importlib.util.spec_from_file_location("getnote_url_workflow_for_tests", SCRIPT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load workflow script at {SCRIPT_PATH}")
workflow = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = workflow
spec.loader.exec_module(workflow)

DESKTOP_SCRIPT_PATH = Path(__file__).parent / "skills" / "getnote-transcribe" / "scripts" / "getnote_desktop_original.py"
desktop_spec = importlib.util.spec_from_file_location("getnote_desktop_original_for_tests", DESKTOP_SCRIPT_PATH)
if desktop_spec is None or desktop_spec.loader is None:
    raise RuntimeError(f"Cannot load desktop original script at {DESKTOP_SCRIPT_PATH}")
desktop_original = importlib.util.module_from_spec(desktop_spec)
sys.modules[desktop_spec.name] = desktop_original
desktop_spec.loader.exec_module(desktop_original)


class GetNoteWorkflowTests(unittest.TestCase):
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
        with tempfile.TemporaryDirectory() as tmp:
            storage_dir = Path(tmp)
            (storage_dir / "000003.log").write_bytes(f"token={older}\ntoken={newer}\ntoken={older}".encode())

            tokens = desktop_original.load_desktop_tokens(storage_dir)

        self.assertEqual(tokens, [newer, older])

    def test_desktop_original_note_id_stays_string(self):
        parser = desktop_original.build_parser()
        args = parser.parse_args(["1912003447071346264"])

        self.assertEqual(args.note_id, "1912003447071346264")

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


if __name__ == "__main__":
    unittest.main()
