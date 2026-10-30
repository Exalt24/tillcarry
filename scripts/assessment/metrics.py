"""Count what is in an OSPOS checkout: files and lines by area, the biggest files, the longest functions and a
crude branch count per file. Pure standard library, prints JSON.

    python scripts/assessment/metrics.py <path to opensourcepos checkout> > docs/evidence/metrics.json

Lines are physical lines of the file; "code lines" skip blank lines and lines that start with a comment marker.
The branch count is the number of if/elseif/for/foreach/while/case/catch/&&/||/?: tokens, which is a rough
stand in for cyclomatic complexity (the real tool run is in docs/evidence/phpmetrics.txt).
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BRANCH = re.compile(r"\b(if|elseif|for|foreach|while|case|catch)\b|&&|\|\||\?[^?]")
FUNC = re.compile(r"^[ \t]*(?:(?:public|protected|private|static)[ \t]+){0,4}function[ \t]+(\w{1,80})[ \t]*\(")


def count(path: Path) -> tuple[int, int]:
    total = code = 0
    for line in path.read_text(encoding="utf8", errors="replace").splitlines():
        total += 1
        s = line.strip()
        if s and not s.startswith(("//", "#", "*", "/*", "<!--")):
            code += 1
    return total, code


def function_lengths(path: Path) -> list[tuple[str, int]]:
    lines = path.read_text(encoding="utf8", errors="replace").splitlines()
    starts = [(i, m.group(1)) for i, ln in enumerate(lines) if (m := FUNC.match(ln))]
    out = []
    for k, (i, name) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        out.append((name, end - i))
    return out


def main(root: Path) -> dict:
    app = root / "application"
    areas = {
        "controllers": app / "controllers",
        "models": app / "models",
        "libraries": app / "libraries",
        "helpers": app / "helpers",
        "views": app / "views",
        "language": app / "language",
        "migrations": app / "migrations",
        "tests": app / "tests",
        "config": app / "config",
    }
    out: dict = {"areas": {}, "biggest_php_files": [], "longest_functions": [], "other": {}}
    allphp: list[tuple[str, int, int, int]] = []
    for name, d in areas.items():
        files = [p for p in d.rglob("*.php")] if d.exists() else []
        tot = cod = 0
        for p in files:
            t, c = count(p)
            tot += t
            cod += c
            text = p.read_text(encoding="utf8", errors="replace")
            allphp.append((str(p.relative_to(root)).replace("\\", "/"), t, c, len(BRANCH.findall(text))))
        out["areas"][name] = {"files": len(files), "lines": tot, "code_lines": cod}
    allphp.sort(key=lambda r: -r[1])
    out["biggest_php_files"] = [{"file": f, "lines": t, "branches": b} for f, t, _c, b in allphp[:12]]
    funcs = []
    for p in list((app / "controllers").rglob("*.php")) + list((app / "models").rglob("*.php")) + list((app / "libraries").rglob("*.php")):
        for name, n in function_lengths(p):
            funcs.append((n, f"{p.relative_to(root)}::{name}".replace("\\", "/")))
    funcs.sort(reverse=True)
    out["longest_functions"] = [{"function": f, "lines": n} for n, f in funcs[:10]]
    out["functions_over_100_lines"] = sum(1 for n, _ in funcs if n > 100)
    out["functions_total"] = len(funcs)
    by_ext: dict[str, int] = defaultdict(int)
    for p in root.rglob("*"):
        if p.is_file() and not any(part in {".git", "vendor", "node_modules", "bower_components"} for part in p.parts):
            by_ext[p.suffix.lower() or "(none)"] += 1
    out["other"]["files_by_extension_top"] = dict(sorted(by_ext.items(), key=lambda kv: -kv[1])[:12])
    out["other"]["sql_files"] = sorted(str(p.relative_to(root)).replace("\\", "/") for p in (root / "database").glob("*.sql"))
    out["other"]["migration_files"] = len(list((app / "migrations").glob("*.php")))
    out["other"]["sql_migration_scripts"] = len(list((app / "migrations" / "sqlscripts").glob("*.sql")))
    out["other"]["test_files"] = [str(p.relative_to(root)).replace("\\", "/") for p in (app / "tests").rglob("*.php")]
    out["other"]["js_test_files"] = sorted(p.name for p in (root / "test").glob("*.js")) if (root / "test").exists() else []
    return out


if __name__ == "__main__":
    json.dump(main(Path(sys.argv[1])), sys.stdout, indent=2)
    print()
