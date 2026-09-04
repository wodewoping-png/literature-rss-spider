import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from classify_daily_zai import pick_latest_daily_csv
from zai_client import ZAIChatClient, ZAIEndpoint, endpoints_from_env


class ZAIDailyPipelineTests(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {"ZAI_API_KEY": "shared-key"},
        clear=True,
    )
    def test_default_endpoint_order(self):
        endpoints = endpoints_from_env()
        self.assertEqual(
            [(endpoint.name, endpoint.base_url, endpoint.protocol) for endpoint in endpoints],
            [
                ("z.ai", "https://api.z.ai/api/paas/v4", "openai"),
                ("bigmodel-openai", "https://open.bigmodel.cn/api/paas/v4", "openai"),
                ("bigmodel-anthropic", "https://open.bigmodel.cn/api/anthropic", "anthropic"),
            ],
        )
        self.assertEqual({endpoint.api_key for endpoint in endpoints}, {"shared-key"})

    def test_pick_latest_daily_csv_uses_date_not_mtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            older = folder / "news_with_abstract_2026-09-02.csv"
            latest = folder / "news_with_abstract_2026-09-03.csv"
            ignored = folder / "news_with_abstract_2026-09-04_translated.csv"
            for path in (older, latest, ignored):
                path.write_text("title\n", encoding="utf-8")
            self.assertEqual(pick_latest_daily_csv(folder), latest)

    @patch("zai_client.requests.post")
    def test_primary_openai_response(self, post: Mock):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        post.return_value = response
        endpoint = ZAIEndpoint("primary", "https://api.z.ai/api/paas/v4", "openai", "secret")
        client = ZAIChatClient(endpoints=[endpoint], model="glm-5.2")

        result = client.generate([{"role": "user", "content": "classify"}])

        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(post.call_args.args[0], "https://api.z.ai/api/paas/v4/chat/completions")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "glm-5.2")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer secret")

    @patch("zai_client.requests.post")
    def test_falls_back_through_bigmodel_openai_to_anthropic(self, post: Mock):
        failed_primary = Mock(status_code=503, text="primary unavailable")
        failed_primary.raise_for_status.side_effect = __import__("requests").HTTPError("503")
        failed_secondary = Mock(status_code=429, text="secondary unavailable")
        failed_secondary.raise_for_status.side_effect = __import__("requests").HTTPError("429")
        succeeded = Mock()
        succeeded.raise_for_status.return_value = None
        succeeded.json.return_value = {"content": [{"type": "text", "text": '{"by_id": {}}'}]}
        succeeded_again = Mock()
        succeeded_again.raise_for_status.return_value = None
        succeeded_again.json.return_value = {"content": [{"type": "text", "text": '{"by_id": {}}'}]}
        post.side_effect = [failed_primary, failed_secondary, succeeded, succeeded_again]
        endpoints = [
            ZAIEndpoint("primary", "https://api.z.ai/api/paas/v4", "openai", "zai-key"),
            ZAIEndpoint("secondary", "https://open.bigmodel.cn/api/paas/v4", "openai", "cn-key"),
            ZAIEndpoint("fallback", "https://open.bigmodel.cn/api/anthropic", "anthropic", "cn-key"),
        ]
        client = ZAIChatClient(endpoints=endpoints, model="glm-5.2")

        result = client.generate(
            [
                {"role": "system", "content": "Return JSON"},
                {"role": "user", "content": "classify"},
            ]
        )

        self.assertEqual(result, '{"by_id": {}}')
        self.assertEqual(post.call_args_list[1].args[0], "https://open.bigmodel.cn/api/paas/v4/chat/completions")
        self.assertEqual(post.call_args_list[2].args[0], "https://open.bigmodel.cn/api/anthropic/v1/messages")
        fallback_call = post.call_args_list[2].kwargs
        self.assertEqual(fallback_call["headers"]["x-api-key"], "cn-key")
        self.assertEqual(fallback_call["json"]["system"], "Return JSON")

        # Once a route succeeds, later classification batches start there.
        self.assertEqual(client.generate([{"role": "user", "content": "next batch"}]), '{"by_id": {}}')
        self.assertEqual(len(post.call_args_list), 4)
        self.assertEqual(post.call_args_list[3].args[0], "https://open.bigmodel.cn/api/anthropic/v1/messages")


if __name__ == "__main__":
    unittest.main()
