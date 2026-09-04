import unittest
from unittest.mock import Mock, patch

import requests

import classify_weekly_onefile as pipeline


class TranslationFallbackTests(unittest.TestCase):
    def test_translation_parser_accepts_compatible_shapes(self):
        self.assertEqual(
            pipeline._translation_list_from_content(
                'Explanation: {"results":[{"translated_text":"甲"},{"text":"乙"}]}',
                2,
            ),
            ["甲", "乙"],
        )

    @patch.object(pipeline, "_call_with_retries", side_effect=[
        '{"translations":["wrong length"]}',
        '{"translations":["甲"]}',
        '{"translations":["乙"]}',
    ])
    def test_invalid_batch_is_split_and_retried(self, call):
        self.assertEqual(pipeline.translate_texts(object(), ["a", "b"], "title"), ["甲", "乙"])
        self.assertEqual(call.call_count, 3)

    @patch.object(pipeline, "translate_texts", return_value=["固态电池电解质"])
    @patch.object(pipeline, "_build_gemini_client", return_value={"client": "test"})
    @patch.object(pipeline, "google_translate_texts", side_effect=RuntimeError("429 Too Many Requests"))
    def test_google_failure_uses_llm_fallback(self, google_translate, build_client, llm_translate):
        original = pipeline.TRANSLATE_FALLBACK_PROVIDER
        pipeline.TRANSLATE_FALLBACK_PROVIDER = "llm"
        try:
            result = pipeline.translate_texts_with_provider(
                None,
                ["Solid-state battery electrolyte"],
                "title",
                "google",
            )
        finally:
            pipeline.TRANSLATE_FALLBACK_PROVIDER = original

        self.assertEqual(result, ["固态电池电解质"])
        google_translate.assert_called_once()
        build_client.assert_called_once()
        llm_translate.assert_called_once_with(
            {"client": "test"},
            ["Solid-state battery electrolyte"],
            "title",
        )

    @patch.object(pipeline.time, "sleep")
    @patch("requests.get")
    def test_google_429_stops_endpoint_retries_immediately(self, get, sleep):
        response = Mock(status_code=429)
        response.raise_for_status.side_effect = requests.HTTPError("429", response=response)
        get.return_value = response

        with self.assertRaises(RuntimeError):
            pipeline.google_translate_texts(["test"], "title")

        get.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
