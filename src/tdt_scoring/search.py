from __future__ import annotations

from pypinyin import Style, lazy_pinyin


def expert_name_search_terms(expert_name: str) -> dict[str, str]:
    normalized_name = "".join(expert_name.casefold().split())
    fallback = lambda text: list(text)
    return {
        "expert_name_pinyin": "".join(
            lazy_pinyin(normalized_name, style=Style.NORMAL, errors=fallback)
        ).casefold(),
        "expert_name_initials": "".join(
            lazy_pinyin(normalized_name, style=Style.FIRST_LETTER, errors=fallback)
        ).casefold(),
    }
