from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .models import ExpertProjectScore, ReviewSession


DEFAULT_OPINION_SAMPLE_POOL = (
    Path(__file__).resolve().parents[2]
    / "var"
    / "review-opinion-samples"
    / "opinion-samples.jsonl"
)
_WRITE_LOCK = Lock()


def _known_sample_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    known: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            sample_id = json.loads(line).get("sample_id")
        except json.JSONDecodeError:
            continue
        if sample_id:
            known.add(str(sample_id))
    return known


def collect_opinion_samples(
    sessions: list[ReviewSession],
    experts: list[ExpertProjectScore],
    path: Path,
) -> int:
    source_names = {
        (session.review_id, session.sheet_name): session.source_name
        for session in sessions
    }
    candidates: list[dict[str, object]] = []
    for expert in experts:
        for scored_session in expert.sessions:
            evidence = scored_session.opinion_evidence
            source_texts = evidence.source_texts or ([evidence.source_text] if evidence.source_text else [])
            if not source_texts:
                continue
            source_name = source_names.get(
                (scored_session.review_id, scored_session.sheet_name), ""
            )
            identity = json.dumps(
                {
                    "source_name": source_name,
                    "sheet_name": scored_session.sheet_name,
                    "project_code": scored_session.project_code,
                    "stage": scored_session.stage,
                    "expert_name": scored_session.expert_name,
                    "source_texts": source_texts,
                    "rule_version": evidence.rule_version,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            candidates.append(
                {
                    "sample_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "rule_version": evidence.rule_version,
                    "source_name": source_name,
                    "sheet_name": scored_session.sheet_name,
                    "project_code": scored_session.project_code,
                    "project_name": scored_session.project_name,
                    "stage": scored_session.stage,
                    "expert_name": scored_session.expert_name,
                    "source_text": evidence.source_text,
                    "source_texts": source_texts,
                    "source_cells": evidence.source_cells
                    or ([evidence.source_cell] if evidence.source_cell else []),
                    "ai_score": scored_session.opinion.score,
                    "ai_level": scored_session.opinion.level,
                    "ai_reason": scored_session.opinion.reason,
                    "zero_reason": evidence.zero_reason,
                    "evidence": {
                        "technical_object": evidence.technical_object,
                        "professional_action": evidence.professional_action,
                        "specific_detail": evidence.specific_detail,
                    },
                    "review_status": "待复核",
                    "human_score": None,
                    "human_note": None,
                }
            )

    if not candidates:
        return 0
    with _WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        known_ids = _known_sample_ids(path)
        deduplicated = {str(item["sample_id"]): item for item in candidates}
        new_samples = [
            item for sample_id, item in deduplicated.items() if sample_id not in known_ids
        ]
        if not new_samples:
            return 0
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for item in new_samples:
                handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        return len(new_samples)
