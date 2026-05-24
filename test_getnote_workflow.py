import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import getnote_url_workflow as workflow


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
            tags=["GetNote转译", "AI"],
        )

        self.assertEqual(
            payload,
            {
                "note_type": "link",
                "link_url": "https://example.com/article",
                "title": "Example title",
                "tags": ["GetNote转译", "AI"],
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


if __name__ == "__main__":
    unittest.main()
