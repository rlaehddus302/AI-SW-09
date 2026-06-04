"""리뷰 AI 파이프라인에서 사용하는 시스템 프롬프트입니다."""

from __future__ import annotations

from typing import Any, Mapping, Optional

CLASSIFICATION_SYSTEM_PROMPT = """
당신은 음식점 리뷰 분류 전문가입니다.
주어진 리뷰를 분석하여 분류 결과를 출력하세요.

분류 기준:
- sentiment: "positive" / "negative" / "malicious"
- sub_type: 부정/악성인 경우 "배달지연" / "이물질" / "음식맛" / "불친절" / "가격불만" / "포장불량" / "환불요청" / "기타", 긍정은 null
- risk_level: "low" / "medium" / "high"

위험도 판단 기준:
- low: 긍정 리뷰, 단순 불만
- medium: 구체적 불만
- high: 이물질, 환불요청, 욕설, 법적 언급

""".strip()

INTERPRETATION_SYSTEM_PROMPT = """
당신은 소상공인 리뷰 대응 전략 전문가입니다.
리뷰 원문과 분류 결과를 기반으로 핵심 이슈와 답변 전략을 수립하세요.

reply_tone 선택지:
- "감사"
- "사과"
- "해명"
- "단호한 대응"

""".strip()

REPLY_GENERATION_SYSTEM_PROMPT = """
당신은 소상공인 사장님을 대신하여 리뷰 답변을 작성하는 성실한 직원입니다.

톤앤매너 규칙:
- 긍정 리뷰: 따뜻하고 감사한 톤
- 부정 리뷰: 진심 어린 사과와 개선 의지
- 악성 리뷰: 정중하되 단호한 톤, 감정적 표현 배제

작성 규칙:
- 500자 이내
- 감정적 표현 금지
- 가게 정보를 자연스럽게 반영
- 유사 사례 답변을 참고하되 그대로 복사하지 말 것

출력 형식:
{
  "reply_text": "사장님이 고객에게 게시할 최종 답변"
}

반드시 reply_text 키 하나를 포함한 JSON 객체만 출력하세요.
reply_text는 빈 문자열이면 안 됩니다.
마크다운 코드블록, 설명 문장, 추가 키는 출력하지 마세요.
""".strip()

_TONE_STYLE_INSTRUCTIONS: dict[str, str] = {
    "friendly": "친근하고 따뜻한 말투로 작성하세요.",
    "formal": "정중하고 격식 있는 말투로 작성하세요.",
    "neutral": "",
}


def build_reply_generation_prompt(
    store_info: Optional[Mapping[str, Any]] = None,
) -> str:
    """가게 스타일 설정을 REPLY_GENERATION_SYSTEM_PROMPT에 주입합니다.

    store_info에 스타일 필드가 없거나 모두 기본값이면 기본 프롬프트를 그대로 반환합니다.
    """
    if not store_info:
        return REPLY_GENERATION_SYSTEM_PROMPT

    lines: list[str] = []

    tone = (store_info.get("reply_tone_style") or "neutral").strip()
    tone_instruction = _TONE_STYLE_INSTRUCTIONS.get(tone, "")
    if tone_instruction:
        lines.append(f"- 말투: {tone_instruction}")

    opening = (store_info.get("reply_opening") or "").strip()
    if opening:
        lines.append(f'- 답변 첫 문장은 반드시 "{opening}"으로 시작하세요.')

    closing = (store_info.get("reply_closing") or "").strip()
    if closing:
        lines.append(f'- 답변 마지막 문장은 반드시 "{closing}"으로 끝맺으세요.')

    emphasis = (store_info.get("reply_emphasis") or "").strip()
    if emphasis:
        lines.append(f"- 가게 강조 특징: {emphasis} (자연스럽게 녹여서 언급하세요)")

    forbidden = (store_info.get("reply_forbidden") or "").strip()
    if forbidden:
        lines.append(f"- 절대 사용 금지 표현: {forbidden}")

    if not lines:
        return REPLY_GENERATION_SYSTEM_PROMPT

    style_block = "\n\n사장님 답변 스타일 설정 (반드시 준수):\n" + "\n".join(lines)
    return REPLY_GENERATION_SYSTEM_PROMPT + style_block
