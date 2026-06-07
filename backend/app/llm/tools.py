from langchain_core.tools import tool
from typing import Any, Dict, List, Optional

@tool
def check_length_N_forbidden(reply_text: str, forbidden_expressions: str) -> Dict[str, Any]:
    """생성한 답변 길이가 500자를 넘는지와 답변에 금지 표현이 포함되어 있는 지를 검사합니다. 

    Args:
        reply_text: 생성한 답변.
        forbidden_expressions: 사용자가 설정한 금지 표현
    """
    if len(reply_text) > 500:
        return {"passed": False, "reason": "답변이 500자를 초과합니다."}
    if forbidden_expressions:
        for expr in (e.strip() for e in forbidden_expressions.split(",") if e.strip()):
            if expr in reply_text:
                return {"passed": False, "reason": f"금지 표현이 포함되어 있습니다: {expr}"}
    return {"passed": True, "reason": None}