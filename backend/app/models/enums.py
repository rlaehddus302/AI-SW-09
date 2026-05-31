from enum import Enum


class OrderType(str, Enum):
    DINE_IN = "dine_in"
    TAKEOUT = "takeout"
    DELIVERY = "delivery"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MALICIOUS = "malicious"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    GENERATING = "generating"
    AUTO_REPLIED = "auto_replied"
    NEEDS_APPROVAL = "needs_approval"
    APPROVED = "approved"
    ON_HOLD = "on_hold"

