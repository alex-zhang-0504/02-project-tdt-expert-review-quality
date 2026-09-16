"""Semantic classifier contract; never substitute keyword scoring for an AI call."""
from .models import OPINION_RULE_VERSION

def validate_predictions(opinions, predictions) -> dict:
    if not isinstance(predictions, list):
        raise ValueError("AI结果必须为列表，未修改统计")
    expected = {o.opinion_id: o for o in opinions}
    output = {}
    for item in predictions:
        if not isinstance(item, dict):
            raise ValueError("AI返回无效记录")
        oid = item.get("id")
        status = item.get("status")
        if not isinstance(oid, str) or not isinstance(status, str) or oid not in expected or oid in output or status not in {"yes", "no", "suspected"}:
            raise ValueError("AI返回的意见身份或状态不合法，未修改统计")
        excerpt, reason = item.get("excerpt", ""), item.get("reason", "")
        if not isinstance(excerpt, str) or not isinstance(reason, str) or not reason.strip():
            raise ValueError("AI结果缺少判定说明")
        if status != "no" and (not excerpt.strip() or excerpt not in expected[oid].text):
            raise ValueError("AI对策片段不是意见原文，未修改统计")
        if excerpt and excerpt not in expected[oid].text:
            raise ValueError("AI证据不在原文中")
        output[oid] = {"status": status, "excerpt": excerpt, "reason": reason,
                       "rule_version": OPINION_RULE_VERSION}
    if output.keys() != expected.keys():
        raise ValueError("AI识别结果存在遗漏，未修改统计")
    return output
