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

    @patch.object(pipeline, "_request_free_translation")
    def test_google_429_rotates_to_another_free_route(self, request_translation):
        response = Mock(status_code=429)
        rate_limit = requests.HTTPError("429", response=response)
        request_translation.side_effect = [rate_limit, "测试"]
        original_routes = pipeline.FREE_TRANSLATE_ROUTES
        original_disabled = set(pipeline._FREE_TRANSLATE_DISABLED_ROUTES)
        original_preferred = pipeline._FREE_TRANSLATE_PREFERRED_ROUTE
        pipeline.FREE_TRANSLATE_ROUTES = ("googleapis", "google")
        pipeline._FREE_TRANSLATE_DISABLED_ROUTES.clear()
        pipeline._FREE_TRANSLATE_PREFERRED_ROUTE = None
        try:
            result = pipeline.google_translate_texts(["test"], "title")
            disabled_after = set(pipeline._FREE_TRANSLATE_DISABLED_ROUTES)
            preferred_after = pipeline._FREE_TRANSLATE_PREFERRED_ROUTE
        finally:
            pipeline.FREE_TRANSLATE_ROUTES = original_routes
            pipeline._FREE_TRANSLATE_DISABLED_ROUTES.clear()
            pipeline._FREE_TRANSLATE_DISABLED_ROUTES.update(original_disabled)
            pipeline._FREE_TRANSLATE_PREFERRED_ROUTE = original_preferred

        self.assertEqual(result, ["测试"])
        self.assertIn("googleapis", disabled_after)
        self.assertEqual(preferred_after, "google")
        self.assertEqual(request_translation.call_args_list[0].args[0], "googleapis")
        self.assertEqual(request_translation.call_args_list[1].args[0], "google")

    def test_mymemory_chunking_obeys_500_byte_limit(self):
        text = "scientific translation " * 80
        chunks = pipeline._split_utf8_chunks(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.encode("utf-8")) <= 450 for chunk in chunks))
        self.assertEqual("".join(chunks).replace(" ", ""), text.replace(" ", ""))

    @patch("requests.get")
    def test_clients5_nested_response_is_parsed(self, get):
        response = Mock()
        response.json.return_value = [["卤化锡钙钛矿光伏电池", "en"]]
        get.return_value = response

        self.assertEqual(
            pipeline._request_free_translation("clients5", "tin perovskite photovoltaics"),
            "卤化锡钙钛矿光伏电池",
        )


if __name__ == "__main__":
    unittest.main()
