#!/usr/bin/env python3
"""Security-control traceability check.

Every control ID in docs/SECURITY_CONTROLS.md must be referenced by the implementation,
and every ID referenced by the implementation must be documented. Keeps the control
matrix honest as the code evolves. Exit code 1 on drift.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ID = re.compile(r"SEC-[A-Z]+-\d{2}")
CODE_PATHS = [
    "backend/app", "frontend/src", "frontend/nginx", "frontend/scripts",
    "backend/Dockerfile", "frontend/Dockerfile", "docker-compose.yml", ".github",
]
SKIP = {"__pycache__", "node_modules", "dist"}
TEXT_EXT = {".py", ".ts", ".tsx", ".mjs", ".conf", ".yml", ".yaml", ""}


def ids_in_code() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for rel in CODE_PATHS:
        base = ROOT / rel
        files = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
        for f in files:
            if SKIP & set(f.parts) or f.suffix not in TEXT_EXT:
                continue
            for cid in ID.findall(f.read_text(errors="ignore")):
                found.setdefault(cid, set()).add(str(f.relative_to(ROOT)))
    return found


def ids_in_docs() -> set[str]:
    text = (ROOT / "docs" / "SECURITY_CONTROLS.md").read_text()
    return {m.group(0) for line in text.splitlines() if line.startswith("|") for m in [ID.search(line)] if m}


def main() -> int:
    code, docs = ids_in_code(), ids_in_docs()
    undocumented = sorted(set(code) - docs)
    unimplemented = sorted(docs - set(code))
    for cid in undocumented:
        print(f"UNDOCUMENTED  {cid}  (used in {', '.join(sorted(code[cid]))})")
    for cid in unimplemented:
        print(f"NOT IN CODE   {cid}  (documented but no implementation references it)")
    if undocumented or unimplemented:
        return 1
    print(f"check_controls: OK - {len(docs)} controls documented and traceable to code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
