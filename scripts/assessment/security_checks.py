"""Offline, grep based security review of an OSPOS checkout. Each check is a named regular expression over a set of
files; the report lists every hit as file:line so a reader can open it and judge. A hit is a lead, not a verdict:
the assessment says which hits were read and confirmed.

    python scripts/assessment/security_checks.py <path to opensourcepos checkout> > docs/evidence/security-grep.txt

Patterns are bounded (no nested quantifiers) and each line is capped before matching.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MAX_LINE = 400
MAX_SHOWN = 6

CHECKS: list[tuple[str, str, str, str]] = [
    # id, glob root, regex, why it matters
    ("sql-concat-in-query", "application", r"->query\([^;]{0,200}(\.\s*\$|\"[^\"]{0,200}\$)", "a raw query built from a variable; safe only if the variable is trusted"),
    ("sql-string-in-where", "application", r"->(where|having|or_where)\(\s*[\"'][^\"']{0,200}\$[a-z_]", "a where clause with a variable inside the string, so the query builder does not escape it"),
    ("sql-interpolated-select", "application", r"->(select|from|join)\(\s*\"[^\"]{0,200}\$[a-z_]", "a select/from/join string that interpolates a variable"),
    ("user-sort-into-order-by", "application/models", r"->order_by\(\s*\$sort", "a column name chosen by the browser (sort=...); depends on the query builder escaping it"),
    ("raw-superglobal", "application", r"\$_(GET|POST|REQUEST|COOKIE|SERVER)\b", "input read without the framework input class (no xss or type filtering)"),
    ("md5-or-sha1", "application", r"\b(md5|sha1)\(", "weak hash; fine for a checksum, wrong for a password"),
    ("weak-random", "application", r"\b(rand|mt_rand|uniqid)\(", "predictable value; wrong for tokens"),
    ("code-execution", "application", r"\b(eval|exec|shell_exec|system|passthru|proc_open|popen|unserialize)\(", "code or command execution, or object injection"),
    ("dynamic-include", "application", r"\b(include|require)(_once)?\s*\(?\s*\$", "an include path built from a variable"),
    ("echo-without-escape", "application/views", r"<\?php echo \$(?!this->lang)[^;?]{0,160}\?>", "output echoed raw; escaping is the view author's job in CodeIgniter 3"),
    ("file-upload", "application", r"\bupload\b[^\n]{0,60}(config|library|allowed_types|do_upload)|do_upload", "an upload entry point"),
    ("allowed-types", "application", r"allowed_types", "which file types an upload accepts"),
    ("redirect-with-input", "application", r"redirect\([^)]{0,80}\$this->input", "redirect to an address taken from the request"),
    ("curl-or-remote-read", "application", r"\b(curl_exec|file_get_contents\(\s*\$|fopen\(\s*\$)", "a server side fetch of a variable address"),
    ("error-display", "application", r"display_errors|error_reporting\(", "where error output is switched on"),
    ("csrf-exclusions", "application/config", r"csrf_exclude_uris|csrf_protection", "which routes skip the CSRF check"),
    ("session-settings", "application/config", r"\$config\['(sess_[a-z_]+|cookie_[a-z_]+|encryption_key)'\]", "session and cookie hardening switches"),
    ("sensitive-in-appconfig", "application", r"smtp_pass|msg_pwd|gcaptcha_secret|mailchimp_api_key", "secrets kept as plain rows in the settings table"),
]


def iter_files(root: Path, sub: str):
    base = root / sub
    for p in sorted(base.rglob("*.php")) if base.is_dir() else [base]:
        if "migrations" in p.parts and sub == "application":
            continue
        yield p


def run(root: Path) -> str:
    out = [f"# OSPOS security grep, root {root.name}", ""]
    for cid, sub, rx, why in CHECKS:
        pat = re.compile(rx, re.IGNORECASE)
        hits = []
        for p in iter_files(root, sub):
            for n, line in enumerate(p.read_text(encoding="utf8", errors="replace").splitlines(), start=1):
                if pat.search(line[:MAX_LINE]):
                    hits.append((str(p.relative_to(root)).replace("\\", "/"), n, line.strip()[:140]))
        out.append(f"## {cid}: {len(hits)} hits ({why})")
        files = sorted({h[0] for h in hits})
        out.append(f"files: {len(files)}")
        for f, n, text in hits[:MAX_SHOWN]:
            out.append(f"  {f}:{n}: {text}")
        if len(hits) > MAX_SHOWN:
            out.append(f"  ... {len(hits) - MAX_SHOWN} more")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf8")
    print(run(Path(sys.argv[1])))
