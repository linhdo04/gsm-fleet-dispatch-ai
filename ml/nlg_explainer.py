"""NLG Explainer — sinh câu giải thích tự nhiên cho gợi ý điều phối tài xế
bằng Claude API (mục "NLG Explainer (LLM)" trong report.md / business_design.md).

Gọi thật `claude-opus-4-8` khi có `ANTHROPIC_API_KEY` trong môi trường; thiếu
key hoặc lỗi mạng/API → fallback về template ghép chuỗi (giữ đúng câu văn cũ
đã dùng trong `ml/export_demo_data.py`), không bao giờ làm sập luồng export
demo data.
"""

from __future__ import annotations

import os
from typing import Optional

import anthropic

MODEL = "claude-opus-4-8"


def _template_explanation(
    target_zone_name: str,
    target_deficit: float,
    driver_id: str,
    from_zone_name: str,
    distance_m: float,
    p_accept: float,
) -> str:
    return (
        f"{target_zone_name} dự kiến thiếu khoảng {target_deficit:.1f} xe. "
        f"Tài xế {driver_id} đang rảnh gần {from_zone_name}, cách {distance_m:.0f}m, "
        f"Acceptance Model dự đoán xác suất chấp nhận {p_accept * 100:.0f}%. "
        f"Gợi ý: di chuyển đến {target_zone_name}."
    )


class ClaudeExplainer:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key else os.environ.get("ANTHROPIC_API_KEY")
        self._client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else None

    def explain_suggestion(
        self,
        target_zone_name: str,
        target_deficit: float,
        driver_id: str,
        from_zone_name: str,
        distance_m: float,
        p_accept: float,
    ) -> str:
        fallback = _template_explanation(
            target_zone_name, target_deficit, driver_id, from_zone_name, distance_m, p_accept
        )
        if self._client is None:
            return fallback

        prompt = (
            "Viết đúng 1 câu tiếng Việt tự nhiên (không xuống dòng, không lời chào, "
            "không giải thích thêm ngoài câu trả lời) thông báo cho tài xế taxi vì sao "
            "hệ thống gợi ý anh/chị di chuyển đến zone này ngay bây giờ.\n\n"
            f"- Zone đích: {target_zone_name}, dự báo thiếu khoảng {target_deficit:.1f} xe\n"
            f"- Tài xế: {driver_id}, đang rảnh gần {from_zone_name}, cách {distance_m:.0f}m\n"
            f"- Acceptance Model dự đoán xác suất tài xế chấp nhận: {p_accept * 100:.0f}%\n"
        )
        try:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=200,
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": prompt}],
            )
        except (anthropic.APIError, anthropic.APIConnectionError):
            return fallback

        for block in response.content:
            if block.type == "text" and block.text.strip():
                return block.text.strip()
        return fallback
