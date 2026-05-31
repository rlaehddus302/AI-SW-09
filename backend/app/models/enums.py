from enum import Enum


class OrderType(str, Enum):
    """리뷰가 발생한 주문 채널을 나타냅니다."""

    DINE_IN = "dine_in"
    TAKEOUT = "takeout"
    DELIVERY = "delivery"


class Sentiment(str, Enum):
    """AI가 분류한 리뷰 감정 유형입니다."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    MALICIOUS = "malicious"


class RiskLevel(str, Enum):
    """AI가 판단한 리뷰 대응 위험도입니다."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReviewStatus(str, Enum):
    """리뷰 분석, 답변 생성, 승인 흐름의 상태값입니다."""

    PENDING = "pending"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    GENERATING = "generating"
    AUTO_REPLIED = "auto_replied"
    NEEDS_APPROVAL = "needs_approval"
    APPROVED = "approved"
    ON_HOLD = "on_hold"
