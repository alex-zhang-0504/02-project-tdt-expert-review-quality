"""Module four: calculate scores from raw facts and saved questionnaires."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .scoring import aggregate
from .scoring_policy import snapshot
from .assessment import selected_experts
from .subjective import require_analysis
from .questionnaire import dimensions, snapshot as questionnaire_snapshot, append_snapshot


STAGE_WEIGHTS = {"TDR1": 4, "TDR2": 2, "TDR3": 4}
RULE_VERSION = "scores-v0.9"
COMPONENTS = (("attendance", "出勤", 5), ("signoff", "会签", 10),
              ("opinion", "意见", 10))


def stage_score(sessions, policy=None):
    policy = policy or snapshot()["parameters"]
    points = policy["components"]
    facts = aggregate(sessions)
    expected, attended, opinions = facts["expected"], facts["attended"], facts["opinions"]
    result = {"applicable": bool(expected), "expected": expected, "attended": attended,
              "opinions": opinions, "suspected": facts["suspected"], "components": {},
              "solutions": facts["solutions"], "solution_bonus": None if facts["pending"] else facts["solutions"] * policy["solution_points"],
              "raw_score": None, "opinion_bonus": 0 if not expected else None, "reasons": []}
    if not expected:
        return result
    reasons = result["reasons"]
    attendance = None if facts["unknown"] else attended / expected * points["attendance"]
    signoff = facts["signed"] / expected * points["signoff"]
    if facts["unknown"]:
        reasons.append("出勤状态未知")
    opinion = 0.0 if not opinions else None if facts["unknown"] or not attended else min(opinions / attended / policy["opinion_threshold"], 1) * points["opinion"]
    if not facts["unknown"] and attended:
        result["opinion_bonus"] = max(opinions - attended * policy["opinion_threshold"], 0) * policy["excess_opinion_points"]
    elif not facts["unknown"]:
        reasons.append("实参为0，评审意见超额得分待确认")
    if opinions and not attended and not facts["unknown"]:
        reasons.append("实参为0但有意见，计分口径待确认")
    if facts["pending"]:
        reasons.append(f"{facts['pending']}条意见待识别对策")
    result["components"] = dict(zip((c[0] for c in COMPONENTS), (attendance, signoff, opinion)))
    if all(value is not None for value in result["components"].values()):
        result["raw_score"] = sum(result["components"].values())
    return result


def questionnaire_score(review, policy=None, questionnaire=None):
    policy = policy or snapshot()["parameters"]
    from .subjective import RULE_VERSION as QUESTION_VERSION, rating_result
    current = review.get('rule_version') == QUESTION_VERSION and (not review.get('questionnaire_hash') or not questionnaire or review['questionnaire_hash'] == questionnaire['sha256'])
    items = [rating_result(d, review.get('ratings', {}).get(d['id'], {}) if current else {}, policy['subjective']) for d in dimensions(receipt=questionnaire)]
    if review and not current:
        for item in items: item['option'] = '旧版问卷待重新确认'
    complete = bool(review.get('evaluator', '').strip()) and all(i['responded'] and i['score'] is not None for i in items)
    return items, sum(i['score'] for i in items) if complete else None


def build_statistics(analysis, scope_confirmed=False):
    require_analysis(analysis)
    scope_confirmed = bool(analysis.assessment.get('confirmed')) or scope_confirmed
    receipt = snapshot(analysis)
    policy = receipt["parameters"]
    weights = policy["stage_weights"]
    precision = policy["precision"]
    minimum = policy["participation"]["minimum_sessions"]
    cap = policy["total_cap"]
    facts_by_name = {e.expert_name: aggregate(e.sessions) for e in selected_experts(analysis)}
    participation_ready = scope_confirmed and not any(f["unknown"] for f in facts_by_name.values())
    tiers = sorted({f["attended"] for f in facts_by_name.values() if f["attended"] >= minimum}, reverse=True)
    rows = []
    for expert in selected_experts(analysis):
        stages = {stage: stage_score([s for s in expert.sessions if s.stage == stage], policy) for stage in weights}
        denominator = sum(weights[stage] for stage, result in stages.items() if result["applicable"])
        facts = facts_by_name[expert.expert_name]
        participation = None
        tier = None
        if participation_ready:
            tier = tiers.index(facts["attended"]) + 1 if facts["attended"] >= minimum else None
            participation = policy["participation"]["tier_scores"][0 if tier == 1 else 1 if tier == 2 else 2]
        reasons, process, objective, bonus, solution_bonus = [], None, None, None, None
        if not scope_confirmed:
            reasons.append("待确认报告范围")
        if not denominator:
            reasons.append("没有适用评审阶段")
        if scope_confirmed and not participation_ready:
            reasons.append("批次存在未知出勤，评审参与度待统计")
        ready = bool(denominator) and all(not r["applicable"] or r["raw_score"] is not None for r in stages.values())
        if ready and scope_confirmed:
            process = sum(r["raw_score"] * weights[stage] / denominator
                            for stage, r in stages.items() if r["applicable"])
            if participation is not None:
                objective = process + participation
        if scope_confirmed and denominator and all(r["opinion_bonus"] is not None for r in stages.values()):
            bonus = sum(r["opinion_bonus"] for r in stages.values())
        if scope_confirmed and denominator and all(r["solution_bonus"] is not None for r in stages.values()):
            solution_bonus = sum(r["solution_bonus"] for r in stages.values())
        for stage, result in stages.items():
            weight = weights[stage] / denominator if result["applicable"] else 0
            reasons.extend(f"{stage}：{reason}" for reason in result["reasons"])
            raw_score = result.pop("raw_score")
            result.update(weight=round(weight * 100, precision), score=None if raw_score is None else round(raw_score, precision),
                          contribution=None if raw_score is None else round(raw_score * weight, precision))
            result["components"] = {key: None if value is None else round(value, precision) for key, value in result["components"].items()}
        review = analysis.subjective_reviews.get(expert.expert_name, {})
        items, subjective = questionnaire_score(review, policy, questionnaire_snapshot(analysis))
        progress = {}
        if analysis.assessment.get('confirmed'):
            from .manager_evaluation import average_review
            items, subjective, progress = average_review(analysis, expert.expert_name, policy)
        if subjective is None:
            reasons.append("主观仍有未回应、依据未齐、旧版问卷或缺少有效评价的题目")
        suspected = sum(r["suspected"] for r in stages.values())
        if suspected:
            reasons.append(f"含{suspected}条待确认对策，疑似尚未计入")
        uncapped = None if any(v is None for v in (objective, subjective, bonus, solution_bonus)) else objective + subjective + bonus + solution_bonus
        if uncapped is not None and uncapped > cap:
            reasons.append(f"合计{uncapped:.2f}分，按{cap}分封顶")
        rows.append({"expert_name": expert.expert_name, "projects": len({s.project_code for s in expert.sessions}),
                     "sessions": len(expert.sessions), "stages": stages,
                     "process_total": None if process is None else round(process, precision),
                     "participation_count": None if facts["unknown"] else facts["attended"],
                     "participation_tier": tier, "participation_score": participation,
                     "objective_total": None if objective is None else round(objective, precision), "opinion_bonus": bonus,
                     "solution_bonus": solution_bonus,
                     "objective_with_rewards": None if any(v is None for v in (objective, bonus, solution_bonus)) else round(objective + bonus + solution_bonus, precision),
                     "proxy_count": sum(bool(s.proxy_name) for s in expert.sessions),
                     "proxy_rate": facts["proxy_rate"], "subjective_progress": progress,
                     "subjective_items": items, "subjective_total": None if subjective is None else round(subjective, precision), "evaluator": review.get("evaluator", ""),
                     "uncapped_total": None if uncapped is None else round(uncapped, precision),
                     "total": None if uncapped is None else round(min(uncapped, cap), precision),
                     "reasons": reasons, "suspected": suspected})
    return {"rule_version": RULE_VERSION, "scope_confirmed": scope_confirmed, "rows": rows, "policy": receipt}


def build_statistics_workbook(analysis, scope_confirmed=False, dimension="all"):
    data = build_statistics(analysis, scope_confirmed)
    if dimension in ('objective', 'subjective'):
        return dimension_workbook(analysis, data, dimension)
    p = data["policy"]["parameters"]
    base = sum(p["components"].values())
    participation_max = p["participation"]["tier_scores"][0]
    subjective_max = sum(v["high"] for v in p["subjective"].values())
    wb = Workbook()
    summary = wb.active
    summary.title = "分数统计（试算）"
    summary.append(["评审人", "项目数", "应参场次", f"TDR1（{base}）", f"TDR2（{base}）", f"TDR3（{base}）",
                    f"阶段加权（{base}）", "总参与评审场次", "参与度数量档", f"评审参与度（{participation_max}）",
                    f"评审过程表现（{base + participation_max}）", f"专业价值贡献（{subjective_max}）", "评审意见超额得分", "输出有效对策得分", "封顶前合计", f"总分（{p['total_cap']}）", "状态与说明"])
    stage_sheet = wb.create_sheet("阶段计分依据")
    stage_sheet.append(["评审人", "阶段", "适用", "应参", "实参", "意见条数", "出勤分", "会签分", "意见基础分", "阶段分", "权重％", "加权贡献", "评审意见超额得分（不加权）", "含对策意见条数", "输出有效对策得分（不加权）", "说明"])
    questionnaire = wb.create_sheet("主观计分依据")
    questionnaire.append(["评审人", "评价人", "维度", "选项", "分值", "依据状态"])
    for row in data["rows"]:
        summary.append([row["expert_name"], row["projects"], row["sessions"],
                        *[row["stages"][stage]["score"] for stage in STAGE_WEIGHTS],
                        row["process_total"], row["participation_count"], row["participation_tier"], row["participation_score"],
                        row["objective_total"], row["subjective_total"], row["opinion_bonus"], row["solution_bonus"], row["uncapped_total"], row["total"],
                        "；".join(row["reasons"]) or "试算"])
        for stage, result in row["stages"].items():
            stage_sheet.append([row["expert_name"], stage, "适用" if result["applicable"] else "不适用",
                                result["expected"], result["attended"], result["opinions"],
                                *[result["components"].get(c[0]) for c in COMPONENTS], result["score"],
                                result["weight"], result["contribution"], result["opinion_bonus"], result["solutions"], result["solution_bonus"], "；".join(result["reasons"])])
        for item in row["subjective_items"]:
            questionnaire.append([row["expert_name"], row["evaluator"], item["dimension"], item["option"],
                                  item["score"], "待补依据" if item["evidence_missing"] else ""])
    info = wb.create_sheet("使用说明")
    info.append(["规则", RULE_VERSION])
    info.append(["配置版本", data['policy']['version']])
    info.append(["配置指纹", data['policy']['sha256']])
    info.append(["实际参数", __import__('json').dumps(data['policy']['parameters'], ensure_ascii=False)])
    append_snapshot(info, analysis)
    info.append(["统计范围", "本次导入的报告，不代表已验证外部报告完整性"])
    for report in analysis.reports:
        info.append(["纳入报告", report.source_name])
    info.append(["范围确认", "已确认本次导入范围" if data["scope_confirmed"] else "未确认，客观总得分与总分留空"])
    info.append(["计分", f"阶段基础{base}分，按配置权重归一加权，再加参与度；前五题逐题有效等权平均，贡献取有效最高分。"])
    info.append(["奖励", f"意见平均数达{p['opinion_threshold']}后，超额每条{p['excess_opinion_points']}分；含对策每条{p['solution_points']}分；总分最高{p['total_cap']}分。"])
    info.append(["参与度", f"至少{p['participation']['minimum_sessions']}场；前两档及其他档分数为{p['participation']['tier_scores']}，并列同分。"])
    info.append(["用途", "结果留档；经理问卷通过独立任务文件回收，不通过评分表回载。"])
    for sheet in wb:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="0A9BF5")
            cell.font = Font(bold=True, color="FFFFFF")
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 22
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def dimension_workbook(analysis, data, dimension):
    import json
    wb = Workbook()
    sheet = wb.active
    sheet.title = '客观评分' if dimension == 'objective' else '主观打分'
    if dimension == 'objective':
        sheet.append(['评审人', 'TDR1', 'TDR2', 'TDR3', '阶段加权', '评审参与度', '基础得分', '评审意见超额得分', '输出有效对策得分', '客观总得分', '状态'])
        for r in data['rows']:
            sheet.append([r['expert_name'], *[r['stages'][s]['score'] for s in STAGE_WEIGHTS],
                r['process_total'], r['participation_score'], r['objective_total'], r['opinion_bonus'], r['solution_bonus'], r['objective_with_rewards'],
                '；'.join(x for x in r['reasons'] if '主观' not in x)])
        facts = wb.create_sheet('数据统计', 0)
        facts.append(['评审人', '统计阶段', '应参场次', '实参场次', '出勤率', '已会签场次', '会签率', '意见条数', '意见提出平均数', '含对策意见条数', '代理场次', '代理率', '待识别条数', '疑似待确认条数', '出勤待确认场次'])
        for expert in selected_experts(analysis):
            for stage in ('全部阶段', *STAGE_WEIGHTS):
                v = aggregate(expert.sessions if stage == '全部阶段' else [s for s in expert.sessions if s.stage == stage])
                facts.append([expert.expert_name, stage, v['expected'], v['attended'],
                    None if v['attendance_rate'] is None else v['attendance_rate']/100,
                    v['signed'], None if v['signoff_rate'] is None else v['signoff_rate']/100,
                    v['opinions'], v['opinion_average'], None if v['pending'] else v['solutions'],
                    v['proxy'], None if v['proxy_rate'] is None else v['proxy_rate']/100,
                    v['pending'], v['suspected'], v['unknown']])
    else:
        sheet.append(['评审人', *[d['title'] for d in dimensions(analysis)], '最终主观分', '暂定平均', '已完成经理数', '应评价经理数', *[d['title']+'有效人数' for d in dimensions(analysis)]])
        for r in data['rows']:
            p = r['subjective_progress']
            sheet.append([r['expert_name'], *[i['score'] for i in r['subjective_items']], r['subjective_total'], p.get('provisional'), p.get('completed'), p.get('expected'), *[i.get('valid_count') for i in r['subjective_items']]])
        detail = wb.create_sheet('经理评价依据')
        detail.append(['经理身份', '经理', '评审人', '维度', '档位', '项目', '依据', '修订', '排除理由', '问卷版本', '题干', '职责边界'])
        from .assessment import is_excluded
        from .subjective import rating_evidence, UNJUDGED, RULE_VERSION as QUESTION_VERSION
        for mid, reviews in analysis.manager_reviews.items():
            for name, review in reviews.items():
                for dim, rating in review['ratings'].items():
                    definition = next(d for d in dimensions(analysis) if d['id'] == dim)
                    label = next((o['title'] for o in definition['options'] if o['id'] == rating['option']), definition['unable_title'] if rating['option']=='unable' else UNJUDGED.get(rating['option'], '待评价'))
                    current = review.get('rule_version') == QUESTION_VERSION
                    if not current: label = '旧版选项（'+rating['option']+'），待重新确认'
                    for evidence in rating_evidence(rating) or [{}]:
                        detail.append([mid, review['evaluator'], name, definition['title'], label, evidence.get('project_code', ''), evidence.get('note', '') or rating.get('reason', ''), review['revision'], is_excluded(analysis, mid, name), review.get('rule_version', ''), definition['prompt'] if current else '', definition['boundary'] if current else ''])
    score_last_row = sheet.max_row
    config = sheet if dimension == 'objective' else wb.create_sheet('配置及范围')
    if dimension == 'objective':
        config.append([])
        config.append(['参数及报告范围'])
    for key, value in data['policy'].items():
        config.append([key, json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value])
    if dimension != 'objective':
        append_snapshot(config, analysis)
    config.append(['考核批次', analysis.assessment.get('batch_id', '')])
    config.append(['名单', '；'.join(analysis.assessment.get('included', []))])
    config.append(['范围确认', data['scope_confirmed']])
    config.append(['统计范围', '本次导入的报告，不代表已验证外部报告完整性'])
    for report in analysis.reports:
        config.append(['纳入报告', report.source_name])
    config.append(['任务排除记录', json.dumps(analysis.assessment.get('exclusions', {}), ensure_ascii=False)])
    for ws in wb:
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns: ws.column_dimensions[col[0].column_letter].width = 24
        for row in ws:
            for cell in row:
                if isinstance(cell.value, str): cell.data_type = 's'
                if isinstance(cell.value, float): cell.number_format = '0' + ('.' + '0' * data['policy']['parameters']['precision'] if data['policy']['parameters']['precision'] else '')
                cell.alignment = Alignment(wrap_text=True, vertical='top')
        for cell in ws[1]:
            cell.fill = PatternFill('solid', fgColor='0A9BF5')
            cell.font = Font(bold=True, color='FFFFFF')
    if dimension == 'objective':
        for cell in sheet[1]:
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        sheet.auto_filter.ref = f'A1:K{score_last_row}'
        sheet.freeze_panes = 'B2'
        for row in sheet.iter_rows(min_row=2, max_row=score_last_row):
            row[9].font = Font(bold=True, color='000000')
        facts.freeze_panes = 'C2'
        for cell in facts[1]:
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        facts.row_dimensions[1].height = 34
        sheet.row_dimensions[1].height = 34
        for col in facts.columns:
            facts.column_dimensions[col[0].column_letter].width = 16
        facts.column_dimensions['A'].width = 22
        for row in facts.iter_rows(min_row=2):
            row[8].number_format = '0.0'
            for index in (4, 6, 11):
                row[index].number_format = '0.0%'
            if row[1].value == '全部阶段':
                for cell in row:
                    cell.fill = PatternFill('solid', fgColor='E6F4FE')
                    cell.font = Font(bold=True, color='000000')
        for index in range(score_last_row + 2, sheet.max_row + 1):
            sheet.merge_cells(start_row=index, start_column=2, end_row=index, end_column=11)
            sheet.row_dimensions[index].height = 120 if sheet.cell(index, 1).value == 'parameters' else 30
        wb.active = 0
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
