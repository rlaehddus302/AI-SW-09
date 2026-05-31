from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class StoreBase(BaseModel):
    store_name: str = Field(min_length=1, max_length=100)
    origin_info: Optional[str] = None
    is_dine_in: bool = False
    is_takeout: bool = False
    is_delivery: bool = False


class StoreCreate(StoreBase):
    pass


class StoreUpdate(StoreBase):
    pass


class StoreRead(StoreBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
