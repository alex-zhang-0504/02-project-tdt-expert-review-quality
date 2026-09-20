"""Consistent dated names for local review exports."""
from datetime import date
import re
from urllib.parse import quote


def review_export_disposition(title, fallback='review.xlsx'):
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip(' .')[:100]
    filename = f'{title}_截止{date.today():%Y年%m月%d日}前的评审记录.xlsx'
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename)}'
