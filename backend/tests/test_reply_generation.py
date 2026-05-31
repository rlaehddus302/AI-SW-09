import pytest

from app.llm.client import LLMResponseParseError
from app.services.reply_generation import extract_reply_text, generate_reply


class FakeReplyClient:
    mode = "live"

    def __init__(self, response):
        self.response = response
        self.payload = None

    def complete_json(self, *, task, system_prompt, user_payload):
        self.payload = user_payload
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def embed_text(self, text, *, purpose="query"):
        return [0.1, 0.2]


def test_extract_reply_text_accepts_live_model_aliases():
    assert extract_reply_text({"reply_text": "정식 답변"}) == "정식 답변"
    assert extract_reply_text({"reply": "별칭 답변"}) == "별칭 답변"
    assert extract_reply_text({"answer": "답변"}) == "답변"


def test_generate_reply_sends_output_schema_and_accepts_alias():
    client = FakeReplyClient({"reply": "방문해 주셔서 감사합니다."})

    result = generate_reply(
        "맛있어요.",
        {"core_issue": "긍정 리뷰", "action_direction": "감사", "reply_tone": "감사"},
        {"store_name": "맛있는 치킨집", "origin_info": "닭고기: 국내산"},
        client=client,
    )

    assert result["reply_text"] == "방문해 주셔서 감사합니다."
    assert client.payload["output_schema"] == {"reply_text": "string, 1~500 chars"}


def test_generate_reply_rejects_empty_or_unparseable_model_response():
    with pytest.raises(ValueError, match="non-empty reply_text"):
        generate_reply(
            "맛있어요.",
            {"core_issue": "긍정 리뷰", "action_direction": "감사", "reply_tone": "감사"},
            {"store_name": "맛있는 치킨집"},
            client=FakeReplyClient({"text": "키가 다릅니다."}),
        )

    with pytest.raises(ValueError, match="must be JSON"):
        generate_reply(
            "맛있어요.",
            {"core_issue": "긍정 리뷰", "action_direction": "감사", "reply_tone": "감사"},
            {"store_name": "맛있는 치킨집"},
            client=FakeReplyClient(LLMResponseParseError("bad json")),
        )
