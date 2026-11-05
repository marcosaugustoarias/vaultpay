"""Architecture test: the domain layer depends on nothing but the standard library.

If someone (human or AI assistant) adds ``import sqlalchemy`` or ``from fastapi ...``
under ``app/domain``, this test fails and the dependency rule of DDD is protected.
"""

import ast
import sys
from pathlib import Path

DOMAIN = Path(__file__).resolve().parents[2] / "app" / "domain"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_domain_imports_only_stdlib_and_itself():
    files = list(DOMAIN.rglob("*.py"))
    assert files, "domain package not found"
    offenders = {}
    for f in files:
        bad = {
            name for name in _imports(f)
            if name.split(".")[0] not in sys.stdlib_module_names
            and not (name == "app.domain" or name.startswith("app.domain."))
        }
        if bad:
            offenders[str(f.relative_to(DOMAIN))] = sorted(bad)
    assert offenders == {}
