import unittest

from backend.app.llm.client import (
    DeterministicMockAIClient,
    LLMConfigurationError,
    LLMResponseParseError,
    UpstageConfig,
    UpstageSolarClient,
    create_ai_client,
)
from backend.app.services.approval_gate import determine_approval
from backend.app.services.classification import classify_review
from backend.app.services.interpretation import analyze_review
from backend.app.services.rag_service import RAGConfig, RAGService
from backend.app.services.reply_generation import generate_reply, generate_reply_pipeline
import backend.app.services.rag_service as rag_module


class AIPipelineTests(unittest.TestCase):
    def test_ai_mode_policy_uses_mock_without_key_in_auto(self):
        client = create_ai_client(UpstageConfig(api_key=None, ai_mode="auto"))

        self.assertIsInstance(client, DeterministicMockAIClient)
        self.assertEqual(client.mode, "mock")

    def test_ai_mode_policy_requires_key_in_live(self):
        with self.assertRaises(LLMConfigurationError):
            create_ai_client(UpstageConfig(api_key=None, ai_mode="live"))

    def test_upstage_json_parse_retries_once(self):
        calls = []

        def fake_post(url, headers, payload, timeout_seconds):
            calls.append((url, headers, payload, timeout_seconds))
            content = "not json" if len(calls) == 1 else '{"sentiment":"positive","risk_level":"low"}'
            return {"choices": [{"message": {"content": content}}]}

        client = UpstageSolarClient(
            UpstageConfig(api_key="up_test", ai_mode="live"),
            http_post=fake_post,
        )

        result = client.complete_json(
            task="classification",
            system_prompt="return json",
            user_payload={"review_text": "맛있어요"},
        )

        self.assertEqual(result, {"sentiment": "positive", "risk_level": "low"})
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][3], 30.0)

    def test_upstage_json_parse_fails_after_one_retry(self):
        def fake_post(url, headers, payload, timeout_seconds):
            return {"choices": [{"message": {"content": "not json"}}]}

        client = UpstageSolarClient(
            UpstageConfig(api_key="up_test", ai_mode="live"),
            http_post=fake_post,
        )

        with self.assertRaises(LLMResponseParseError):
            client.complete_json(
                task="classification",
                system_prompt="return json",
                user_payload={"review_text": "맛있어요"},
            )

    def test_mock_classification_is_deterministic_and_normalized(self):
        client = DeterministicMockAIClient()

        first = classify_review("배달이 1시간 늦고 음식이 식었어요", client=client)
        second = classify_review("배달이 1시간 늦고 음식이 식었어요", client=client)

        self.assertEqual(first, second)
        self.assertEqual(
            first,
            {
                "sentiment": "negative",
                "sub_type": "배달지연",
                "risk_level": "medium",
            },
        )

    def test_empty_review_text_is_rejected(self):
        with self.assertRaises(ValueError):
            classify_review("", client=DeterministicMockAIClient())

    def test_approval_gate_only_auto_replies_low_positive(self):
        cases = [
            ("low", "positive", "auto_replied"),
            ("low", "negative", "needs_approval"),
            ("medium", "positive", "needs_approval"),
            ("high", "negative", "needs_approval"),
            ("low", "malicious", "needs_approval"),
            (None, None, "needs_approval"),
        ]

        for risk_level, sentiment, expected in cases:
            with self.subTest(risk_level=risk_level, sentiment=sentiment):
                self.assertEqual(determine_approval(risk_level, sentiment), expected)

    def test_rag_seed_search_and_add_contract_with_mock_fallback(self):
        rag = RAGService(
            client=DeterministicMockAIClient(),
            config=RAGConfig(ai_mode="mock"),
        )
        count = rag.seed(
            [
                {
                    "review": "배달이 너무 늦었어요",
                    "reply": "배달 지연으로 불편을 드려 죄송합니다.",
                    "sub_type": "배달지연",
                    "risk_level": "medium",
                    "order_type": "delivery",
                },
                {
                    "review": "치킨이 바삭하고 맛있어요",
                    "reply": "맛있게 드셔서 감사합니다.",
                    "sub_type": None,
                    "risk_level": "low",
                    "order_type": "delivery",
                },
            ]
        )

        added_id = rag.add(
            review="포장 국물이 다 샜어요",
            reply="포장 불량으로 불편을 드려 죄송합니다.",
            sub_type="포장불량",
            risk_level="medium",
            order_type="delivery",
        )
        results = rag.search("배달이 1시간이나 늦었습니다", top_k=2, order_type="delivery")

        self.assertEqual(count, 2)
        self.assertTrue(added_id.startswith("rag_"))
        self.assertEqual(len(results), 2)
        self.assertEqual(
            set(results[0]),
            {
                "review",
                "reply",
                "sub_type",
                "risk_level",
                "order_type",
                "similarity",
            },
        )

    def test_rag_skips_empty_seed_and_handles_zero_limit(self):
        rag = RAGService(
            client=DeterministicMockAIClient(),
            config=RAGConfig(ai_mode="mock"),
        )

        count = rag.seed(
            [
                {"review": "", "reply": "빈 리뷰"},
                {"review": "맛있어요", "reply": ""},
                {"review": "맛있어요", "reply": "감사합니다.", "risk_level": "low"},
            ]
        )

        self.assertEqual(count, 1)
        self.assertEqual(rag.search("맛있어요", top_k=0), [])

    def test_rag_adapter_functions_match_backend_contract(self):
        previous_service = rag_module._default_rag_service
        rag_module._default_rag_service = RAGService(
            client=DeterministicMockAIClient(),
            config=RAGConfig(ai_mode="mock"),
        )
        try:
            rag_module.seed_rag_pairs(
                [
                    {
                        "review": "배달이 늦었어요",
                        "reply": "배달 지연으로 불편을 드려 죄송합니다.",
                        "sub_type": "배달지연",
                        "risk_level": "medium",
                        "order_type": "delivery",
                    }
                ],
                store_id=7,
            )
            rag_module.save_approved_reply(
                review="포장이 샜어요",
                reply="포장 상태를 개선하겠습니다.",
                store_id=7,
                sub_type="포장불량",
                risk_level="medium",
                order_type="delivery",
            )
            results = rag_module.search_similar_reviews(
                review_text="배달이 너무 지연됐어요",
                store_id=7,
                sub_type="배달지연",
                order_type="delivery",
                limit=1,
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["sub_type"], "배달지연")
        finally:
            rag_module._default_rag_service = previous_service

    def test_analysis_and_reply_pipeline_shapes_for_router_integration(self):
        client = DeterministicMockAIClient()
        analysis = analyze_review("치킨이 정말 바삭하고 맛있어요!", client=client)
        rag = RAGService(client=client, config=RAGConfig(ai_mode="mock"))

        result = generate_reply_pipeline(
            "치킨이 정말 바삭하고 맛있어요!",
            analysis["classification"],
            analysis["interpretation"],
            {"store_name": "맛있는 치킨집"},
            order_type="delivery",
            rag_service=rag,
            client=client,
        )

        self.assertEqual(analysis["classification"]["sentiment"], "positive")
        self.assertEqual(result["status"], "auto_replied")
        self.assertIn("맛있는 치킨집", result["reply_text"])
        self.assertEqual(result["rag_references"], [])

    def test_reply_generation_parse_failure_returns_empty_draft(self):
        class BrokenReplyClient(DeterministicMockAIClient):
            def complete_json(self, *, task, system_prompt, user_payload):
                raise LLMResponseParseError("broken")

        result = generate_reply(
            "맛있어요",
            {"core_issue": "긍정 경험", "action_direction": "감사", "reply_tone": "감사"},
            {"store_name": "맛있는 치킨집"},
            client=BrokenReplyClient(),
        )

        self.assertEqual(result, {"reply_text": "", "rag_references": []})


if __name__ == "__main__":
    unittest.main()
