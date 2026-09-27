"""Six-dimension human assessment, separate from V0.6 fact statistics."""
from datetime import datetime, timezone
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import BaseModel, ConfigDict, Field


RULE_VERSION = "subjective-v0.9"
from .questionnaire import dimensions, snapshot as questionnaire_snapshot
DIMENSIONS = dimensions()

UNJUDGED = {"unable": "暂无法判断", "no_opportunity": "本期无相关职责／机会"}

class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_code: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=100)


class RatingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option: str
    reason: str = Field(default="", max_length=500)
    evidence: list[EvidenceInput] = Field(default_factory=list)
    project_code: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=100)


class ReviewInput(BaseModel):
    expected_revision: int | None = Field(default=None, ge=0)
    questionnaire_hash: str = ""
    model_config = ConfigDict(extra="forbid")
    rule_version: str = RULE_VERSION
    analysis_id: str = Field(min_length=1)
    expert_name: str = Field(min_length=1)
    evaluator: str = Field(min_length=1, max_length=80)
    ratings: dict[str, RatingInput]
    manager_id: str = ""


def require_analysis(analysis):
    if any(issue.severity == "error" for issue in analysis.issues):
        raise ValueError("请先处理报告中的阻断问题")


def rating_evidence(rating):
    rows = list(rating.get('evidence', []))
    if rating.get('project_code') or rating.get('note'):
        rows.insert(0, {'project_code': rating.get('project_code', ''), 'note': rating.get('note', '')})
    return [r for r in rows if r.get('project_code', '').strip() or r.get('note', '').strip()]


def rating_result(dimension, rating, policy=None):
    code = rating.get('option')
    option = next((o for o in dimension['options'] if o['id'] == code), None)
    skipped = dimension['id'] != 'contribution' and code in UNJUDGED
    evidence = rating_evidence(rating)
    required = code in dimension.get('required_options', [] if dimension['id'] == 'preparation' else ['high'] if dimension['id'] == 'contribution' else ['low'])
    missing = (skipped and not rating.get('reason', '').strip()) or (not skipped and required and (
        not evidence or any(not e.get('project_code', '').strip() or not e.get('note', '').strip() for e in evidence)))
    responded = bool(option or skipped) and not missing
    score = (policy[dimension['id']][code] if policy else option['score']) if option and responded else None
    return {'dimension': dimension['title'], 'option': option['title'] if option else dimension.get('unable_title', UNJUDGED['unable']) if code == 'unable' else UNJUDGED.get(code, '待评价'),
            'score': score, 'evidence_missing': bool(missing), 'responded': responded,
            'response_state': code or 'unanswered'}


def save_review(analysis, payload: ReviewInput) -> dict:
    require_analysis(analysis)
    if payload.rule_version != RULE_VERSION:
        raise ValueError("问卷版本已变化，请按新题重新确认")
    expert = next((e for e in analysis.experts if e.expert_name == payload.expert_name), None)
    if expert is None:
        raise ValueError("评审人不属于当前分析")
    if not payload.evaluator.strip():
        raise ValueError("请填写评价人")
    definition = questionnaire_snapshot(analysis)
    if payload.questionnaire_hash and payload.questionnaire_hash != definition["sha256"]:
        raise ValueError("问卷内容版本不一致，请重新打开本次考核问卷")
    current_dimensions = dimensions(analysis)
    catalog = {d["id"]: d for d in current_dimensions}
    if payload.ratings.keys() - catalog.keys():
        raise ValueError("存在未知评分维度")
    projects = {s.project_code for s in expert.sessions}
    if analysis.assessment.get('confirmed'):
        from .assessment import manager_task, is_excluded
        manager = manager_task(analysis, payload.manager_id, payload.expert_name)
        if is_excluded(analysis, payload.manager_id, payload.expert_name):
            raise ValueError('该评价任务已排除，请先恢复任务')
        projects = set(manager['experts'][payload.expert_name])
        if payload.evaluator.strip() != manager['name']:
            raise ValueError('评价人必须与项目经理身份一致')
    ratings = {}
    for dimension_id, rating in payload.ratings.items():
        option = next((o for o in catalog[dimension_id]["options"] if o["id"] == rating.option), None)
        if option is None and not (dimension_id != 'contribution' and rating.option in UNJUDGED):
            raise ValueError("该维度不存在所选行为或回应状态")
        evidence = [dict(project_code=e.project_code.strip(), note=e.note.strip()) for e in rating.evidence if e.project_code.strip() or e.note.strip()]
        project, note = rating.project_code.strip(), rating.note.strip()
        if project or note:
            evidence.insert(0, dict(project_code=project, note=note))
        if any(e['project_code'] and e['project_code'] not in projects for e in evidence):
            raise ValueError("关联项目不属于该经理与评审人的共同项目范围")
        ratings[dimension_id] = {"option": rating.option, "project_code": project, "note": note}
        if rating.evidence: ratings[dimension_id]['evidence'] = [dict(project_code=e.project_code.strip(), note=e.note.strip()) for e in rating.evidence]
        if rating.reason: ratings[dimension_id]['reason'] = rating.reason.strip()
    checks = [rating_result(d, ratings.get(d['id'], {})) for d in current_dimensions]
    status = '已完成' if all(i['responded'] for i in checks) else '待评价' if len(ratings) < len(DIMENSIONS) else '待补依据'
    record = {"rule_version": RULE_VERSION, "evaluator": payload.evaluator.strip(),
              "ratings": ratings, "status": status, "questionnaire_hash": definition["sha256"],
              "updated_at": datetime.now(timezone.utc).isoformat()}
    if analysis.assessment.get('confirmed'):
        records = analysis.manager_reviews.setdefault(payload.manager_id, {})
        record['revision'] = records.get(payload.expert_name, {}).get('revision', 0) + 1
        record['manager_id'] = payload.manager_id
        records[payload.expert_name] = record
    else:
        analysis.subjective_reviews[payload.expert_name] = record
    return record


def build_workbook(analysis) -> bytes:
    require_analysis(analysis)
    wb = Workbook()
    summary = wb.active
    summary.title = "主观问卷"
    summary.append(["评审人", "评价人", "状态", "参评项目范围", "更新时间", "规则版本"])
    detail = wb.create_sheet("选档与依据")
    detail.append(["评审人", "维度", "选项", "项目编码", "事实依据", "条目解释"])
    for expert in analysis.experts:
        review = analysis.subjective_reviews.get(expert.expert_name, {})
        projects = sorted({f"{s.project_name}（{s.project_code}）" for s in expert.sessions})
        summary.append([expert.expert_name, review.get("evaluator", ""), review.get("status", "待评价"),
                        "；".join(projects), review.get("updated_at", ""), review.get("rule_version", "")])
        for dimension in dimensions(analysis):
            rating = review.get("ratings", {}).get(dimension["id"], {})
            option = next((o for o in dimension["options"] if o["id"] == rating.get("option")), {})
            label = option.get("title", UNJUDGED.get(rating.get("option"), "待评价"))
            if rating and review.get("rule_version") != RULE_VERSION: label = "旧版选项（" + rating.get("option", "") + "），待重新确认"
            detail.append([expert.expert_name, dimension["title"], label,
                           "；".join(e["project_code"] for e in rating_evidence(rating)), "；".join(e["note"] for e in rating_evidence(rating)) or rating.get("reason", ""),
                           option.get("description", "")])
    info = wb.create_sheet("使用说明")
    info.append(["评价范围", analysis.source_name])
    info.append(["保存用途", "本文件用于主观评价查阅留档，不支持自动合并或回载；未完成评价不产生主观总分。"])
    info.append(["计分位置", "本文件只保存问卷，分数统一在第四模块分数统计计算与导出。"])
    for sheet in wb:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for cell in sheet[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = PatternFill("solid", fgColor="0A9BF5")
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 22 if column[0].column < 5 else 48
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
