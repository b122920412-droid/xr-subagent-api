from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def _clean_vec(value: Any, field: str, *, positive: bool) -> list[float]:
    """共用的三維向量驗證器。positive=True 時額外要求每個元素 > 0。"""
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} 必須是長度為 3 的陣列")
    if len(value) != 3:
        raise ValueError(f"{field} 必須剛好 3 個元素")

    result: list[float] = []
    for item in value:
        # bool 是 int 的子類別，必須明確排除
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{field} 元素必須是數字，不接受字串或布林值")
        try:
            num = float(item)
        except (OverflowError, ValueError):
            raise ValueError(f"{field} 元素必須是有限數（不可為 NaN / Infinity）")
        if not math.isfinite(num):
            raise ValueError(f"{field} 元素必須是有限數（不可為 NaN / Infinity）")
        if positive and num <= 0:
            raise ValueError("scale 元素必須嚴格大於 0")
        result.append(num)
    return result


class ObjectBase(BaseModel):
    # from_attributes：讓 ObjectOut 可用 model_validate(dict)
    # extra="forbid"：客戶端不得送出 id 或任何未知欄位 → 422
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    name: str
    model_url: str
    position: list[float]
    rotation: list[float]
    scale: list[float]

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        s = v.strip()
        if not (1 <= len(s) <= 100):
            raise ValueError("name 去除前後空白後長度必須為 1–100，且不可為空")
        return s

    @field_validator("model_url")
    @classmethod
    def _validate_model_url(cls, v: str) -> str:
        if not (1 <= len(v) <= 500):
            raise ValueError("model_url 長度必須為 1–500")
        if not (v.startswith("http://") or v.startswith("https://") or v.startswith("/")):
            raise ValueError("model_url 必須以 http://、https:// 或 / 開頭")
        return v

    @field_validator("position", "rotation", mode="before")
    @classmethod
    def _validate_vec3(cls, v: Any, info: Any) -> list[float]:
        # mode="before"：在 Pydantic 自動把 "1" 轉成 1.0 之前先攔截字串
        return _clean_vec(v, info.field_name, positive=False)

    @field_validator("scale", mode="before")
    @classmethod
    def _validate_scale(cls, v: Any) -> list[float]:
        return _clean_vec(v, "scale", positive=True)


class ObjectCreate(ObjectBase):
    pass


class ObjectUpdate(ObjectBase):
    pass


class ObjectOut(ObjectBase):
    id: int
