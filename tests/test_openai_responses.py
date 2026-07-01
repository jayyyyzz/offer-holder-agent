from unittest import mock
from pathlib import Path
import tempfile
import unittest

from agent.openai_responses import (
    build_responses_payload,
    extract_incomplete_reason,
    extract_output_text,
    generate_grounded_response,
    write_openai_run_metadata,
)


class OpenAIResponsesTests(unittest.TestCase):
    def test_build_responses_payload_uses_model_and_prompt(self) -> None:
        payload = build_responses_payload("hello world", model="gpt-5.5", max_output_tokens=200)
        self.assertEqual(payload["model"], "gpt-5.5")
        self.assertEqual(payload["input"], "hello world")
        self.assertEqual(payload["max_output_tokens"], 200)
        self.assertEqual(payload["reasoning"]["effort"], "medium")
        self.assertEqual(payload["text"]["verbosity"], "low")

    def test_extract_output_text_prefers_output_text(self) -> None:
        payload = {"output_text": "final answer"}
        self.assertEqual(extract_output_text(payload), "final answer")

    def test_extract_output_text_falls_back_to_output_blocks(self) -> None:
        payload = {
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "第一段"},
                        {"type": "output_text", "text": {"value": "第二段"}},
                    ]
                }
            ]
        }
        self.assertIn("第一段", extract_output_text(payload))
        self.assertIn("第二段", extract_output_text(payload))

    def test_extract_incomplete_reason_reads_incomplete_details(self) -> None:
        payload = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
        self.assertEqual(extract_incomplete_reason(payload), "max_output_tokens")

    @mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @mock.patch("agent.openai_responses.requests.post")
    def test_generate_grounded_response_retries_transient_http_error(self, mock_post) -> None:
        first = mock.Mock()
        first.status_code = 429
        first.raise_for_status.side_effect = mock.Mock(side_effect=Exception("429"))

        second = mock.Mock()
        second.status_code = 200
        second.raise_for_status.return_value = None
        second.json.return_value = {"output_text": "ok"}

        def raise_http_error():
            import requests
            response = mock.Mock()
            response.status_code = 429
            raise requests.HTTPError(response=response)

        first.raise_for_status.side_effect = raise_http_error
        mock_post.side_effect = [first, second]

        text, payload = generate_grounded_response("hello", max_retries=1, retry_backoff_seconds=0)
        self.assertEqual(text, "ok")
        self.assertEqual(payload["output_text"], "ok")
        self.assertEqual(mock_post.call_count, 2)

    @mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @mock.patch("agent.openai_responses.requests.post")
    def test_generate_grounded_response_populates_run_metadata(self, mock_post) -> None:
        response = mock.Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "id": "resp_123",
            "status": "completed",
            "output_text": "final grounded answer",
        }
        mock_post.return_value = response

        metadata: dict[str, object] = {}
        text, _ = generate_grounded_response(
            "hello",
            max_retries=0,
            retry_backoff_seconds=0,
            run_metadata=metadata,
        )

        self.assertEqual(text, "final grounded answer")
        self.assertEqual(metadata["status"], "success")
        self.assertEqual(metadata["response_id"], "resp_123")
        self.assertEqual(metadata["attempt_count"], 1)
        self.assertIn("output_excerpt", metadata)

    def test_write_openai_run_metadata_creates_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = write_openai_run_metadata(
                {
                    "status": "success",
                    "response_id": "resp_456",
                    "model": "gpt-5.5",
                },
                output_dir=Path(tmp),
            )
            self.assertTrue(output_path.exists())
            content = output_path.read_text(encoding="utf-8")
            self.assertIn("\"response_id\": \"resp_456\"", content)


if __name__ == "__main__":
    unittest.main()
