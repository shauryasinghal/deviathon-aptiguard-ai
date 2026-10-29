"""Fail if tracked (or staged/untracked-but-not-ignored) files contain secrets or local artifacts.

Usage: python3 scripts/check_repo_hygiene.py      (exit 0 = clean, 1 = findings)
Scans the files Git would commit: `git ls-files --cached --others --exclude-standard`.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PATHS = [
    (re.compile(r"(^|/)\.env(\.[^/]*)?$"), "environment file"),
    (re.compile(r"\.(db|sqlite3?)(-wal|-shm|-journal)?$"), "database file"),
    (re.compile(r"(^|/)(node_modules|\.venv|venv|__pycache__|\.pytest_cache)/"), "dependency/cache directory"),
    (re.compile(r"(^|/)backend/var/"), "local runtime data"),
    (re.compile(r"(^|/)backups?/"), "backup"),
    (re.compile(r"(^|/)(dist|test-results|playwright-report)/"), "build/test artifact"),
    (re.compile(r"\.(pem|key|p12|pfx)$"), "key material"),
]
ALLOWED_PATHS = {".env.example"}

SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API key"),
    (re.compile(r"\bsk-[A-Za-z0-9]{32,}"), "API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^:\s/]+:(?!\$\{|<|USER|PASSWORD|\*\*\*)[^@\s]{6,}@"), "database URL with password"),
    (re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}"), "bcrypt hash"),
    (re.compile(r"/Users/[A-Za-z0-9._-]+/"), "absolute local path"),
]


def files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def main() -> int:
    findings = []
    for f in files():
        if f not in ALLOWED_PATHS:
            for rx, what in FORBIDDEN_PATHS:
                if rx.search(f):
                    findings.append(f"{f}: {what} must not be committed")
        p = ROOT / f
        if not p.is_file() or p.stat().st_size > 20_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if f == "scripts/check_repo_hygiene.py":
            continue  # contains the patterns themselves
        for n, line in enumerate(text.splitlines(), 1):
            for rx, what in SECRET_PATTERNS:
                if rx.search(line):
                    findings.append(f"{f}:{n}: possible {what}")
    if findings:
        print("Repository hygiene check FAILED:")
        print("\n".join(f"  - {x}" for x in findings[:100]))
        return 1
    print(f"Repository hygiene check passed ({len(files())} files scanned).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
