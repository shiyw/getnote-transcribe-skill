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


if __name__ == "__main__":
    unittest.main()
