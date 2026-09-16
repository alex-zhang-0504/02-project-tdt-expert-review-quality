"""V0.6 fact aggregation. No scoring or ranking."""
from __future__ import annotations

from hashlib import sha256

from .models import ExpertFacts, OpinionFact, ReviewSession, SessionFact

STAGES = ("TDR1", "TDR2", "TDR3")
ATTENDED = {"正常", "部分参加", "改派（正常）", "改派（部分）"}
ABSENT = {"缺席未改派", "挂会"}
EMPTY_SIGNOFF = {"", "-", "－", "—", "–"}


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 2) if denominator else None


def aggregate(sessions: list[SessionFact]) -> dict:
    expected = len(sessions)
    attended = sum(s.attended is True for s in sessions)
    unknown = sum(s.attended is None for s in sessions)
    signed = sum(s.signed for s in sessions)
    opinions = [o for s in sessions for o in s.opinions]
    pending = sum(o.ai_status == "pending" for o in opinions)
    solutions = sum(o.ai_status != "pending" and (o.included is True or (o.included is None and o.ai_status == "yes")) for o in opinions)
    suspected = sum(o.ai_status == "suspected" and o.included is None for o in opinions)
    proxy = sum(bool(s.proxy_name) for s in sessions)
    return {
        "expected": expected, "attended": attended, "unknown": unknown,
        "signed": signed, "opinions": len(opinions), "solutions": solutions,
        "suspected": suspected, "pending": pending, "proxy": proxy,
        "projects": len({s.project_code for s in sessions}),
        "attendance_rate": None if unknown else ratio(attended, expected),
        "signoff_rate": ratio(signed, expected),
        "opinion_rate": None if unknown else ratio(len(opinions), attended),
        "solution_rate": None if pending or not solutions else ratio(solutions, len(opinions)),
        "proxy_rate": ratio(proxy, expected),
    }


def refresh(experts: list[ExpertFacts]) -> None:
    for expert in experts:
        expert.stages = {stage: aggregate([s for s in expert.sessions if s.stage == stage]) for stage in STAGES}
        expert.overall = aggregate(expert.sessions)
    experts.sort(key=lambda e: (-e.overall["attended"], e.expert_name))


def build_facts(sessions: list[ReviewSession], decisions: dict | None = None) -> list[ExpertFacts]:
    from .excel_reader import normalize_opinion_key, split_opinion_items
    from .models import OpinionSource

    grouped: dict[str, ExpertFacts] = {}
    seen = set()
    for session in sessions:
        for signoff in session.signoffs:
            name = signoff.expert_name
            key = (session.review_id, name)
            if not name or key in seen:
                continue
            seen.add(key)
            expert = grouped.setdefault(name, ExpertFacts(name, [], {}, {}))
            sources = signoff.opinion_sources
            if not sources:
                sources = [
                    OpinionSource(text, [signoff.opinion_cell] if signoff.opinion_cell else [], [signoff.basis])
                    for text in split_opinion_items(signoff.basis)
                ]
            opinions: dict[str, OpinionFact] = {}
            for source in sources:
                normalized = normalize_opinion_key(source.text)
                if not normalized:
                    continue
                if normalized in opinions:
                    existing = opinions[normalized]
                    existing.cells = list(dict.fromkeys(existing.cells + source.cell_references))
                    existing.raw_texts = list(dict.fromkeys(existing.raw_texts + source.raw_texts))
                    continue
                oid = sha256(f"{session.review_id}\0{name}\0{normalized}".encode()).hexdigest()[:24]
                opinion = OpinionFact(oid, source.text, list(source.cell_references), list(source.raw_texts))
                if decisions and oid in decisions:
                    saved = decisions[oid]
                    for field in ("ai_status", "excerpt", "reason", "rule_version", "included", "audit"):
                        if field in saved:
                            setattr(opinion, field, saved[field])
                opinions[normalized] = opinion
            attendance = signoff.attendance
            attended = True if attendance in ATTENDED else False if attendance in ABSENT else None
            expert.sessions.append(SessionFact(
                session.review_id, session.project_code, session.project_name,
                session.stage, session.sheet_name, session.source_name,
                attendance, attended, signoff.conclusion_raw,
                signoff.conclusion_raw.strip() not in EMPTY_SIGNOFF,
                signoff.proxy_name, list(opinions.values()), dict(signoff.cell_references),
            ))
    experts = list(grouped.values())
    refresh(experts)
    return experts


def decision_payload(experts: list[ExpertFacts]) -> dict:
    from dataclasses import asdict
    return {o.opinion_id: asdict(o) for e in experts for s in e.sessions for o in s.opinions}
