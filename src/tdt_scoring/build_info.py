from __future__ import annotations

from hashlib import sha256
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "tdt-expert-review-quality"


def calculate_build_id(project_root: Path = PROJECT_ROOT) -> str:
    runtime_files = [
        *sorted((project_root / "src" / "tdt_scoring").rglob("*.py")),
        *sorted((project_root / "src" / "web").glob("*")),
    ]
    digest = sha256()
    for path in runtime_files:
        if not path.is_file():
            continue
        digest.update(path.relative_to(project_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


BUILD_ID = calculate_build_id()
