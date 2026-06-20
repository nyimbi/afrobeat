#!/usr/bin/env python3
"""Zero-downtime migration safety checker (FMEA D03).

Scans Alembic migration files for operations that would break a rolling deploy
where old application code and new code run simultaneously against the same DB.

Run in CI before every deploy:
    python scripts/migration_safety_check.py

Exit code:
    0  — all migrations pass
    1  — at least one UNSAFE pattern found (blocks deploy)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations" / "versions"

# Patterns that are unsafe during a zero-downtime rolling deploy.
# Each entry: (pattern_regex, explanation, severity)
UNSAFE_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"op\.drop_column\s*\(", re.IGNORECASE),
        "DROP COLUMN — old pods still reference this column; defer to a follow-up migration "
        "after 100% of pods run new code.",
        "UNSAFE",
    ),
    (
        re.compile(r"op\.drop_table\s*\(", re.IGNORECASE),
        "DROP TABLE — same concern as DROP COLUMN.",
        "UNSAFE",
    ),
    (
        re.compile(r"op\.alter_column.*nullable\s*=\s*False", re.IGNORECASE),
        "Adding NOT NULL constraint — fails if any old pod inserts a NULL row. "
        "Add DEFAULT or backfill first.",
        "UNSAFE",
    ),
    (
        re.compile(r"op\.rename_table\s*\(", re.IGNORECASE),
        "RENAME TABLE — breaks old code that references the original name.",
        "UNSAFE",
    ),
    (
        re.compile(r"server_default\s*=\s*None.*nullable\s*=\s*False", re.IGNORECASE),
        "NOT NULL column with no server_default — new rows from old pods will fail.",
        "UNSAFE",
    ),
    (
        re.compile(r"op\.create_index\b(?!.*concurrently)", re.IGNORECASE),
        "CREATE INDEX without CONCURRENTLY — locks the table and blocks reads/writes. "
        "Use op.create_index(..., postgresql_concurrently=True).",
        "WARN",
    ),
    (
        re.compile(r"op\.drop_constraint\s*\(", re.IGNORECASE),
        "DROP CONSTRAINT — verify old code does not depend on this constraint for data integrity.",
        "WARN",
    ),
]


def check_migration(path: Path) -> list[tuple[str, str, str]]:
    """Return list of (line, description, severity) tuples for violations found."""
    violations: list[tuple[str, str, str]] = []
    text = path.read_text()
    # Only scan the upgrade() function body
    upgrade_match = re.search(r"def upgrade\(\).*?(?=^def |\Z)", text, re.DOTALL | re.MULTILINE)
    body = upgrade_match.group(0) if upgrade_match else text

    for pattern, description, severity in UNSAFE_PATTERNS:
        for match in pattern.finditer(body):
            # Get the line content for context
            start = body.rfind("\n", 0, match.start()) + 1
            end = body.find("\n", match.end())
            line_text = body[start:end].strip()
            violations.append((line_text, description, severity))

    return violations


def main() -> int:
    if not MIGRATIONS_DIR.exists():
        print(f"[ERROR] Migrations directory not found: {MIGRATIONS_DIR}")
        return 1

    migration_files = sorted(MIGRATIONS_DIR.glob("*.py"))
    if not migration_files:
        print("[OK] No migration files found.")
        return 0

    total_unsafe = 0
    total_warn = 0

    for migration_file in migration_files:
        violations = check_migration(migration_file)
        if not violations:
            continue

        unsafe = [v for v in violations if v[2] == "UNSAFE"]
        warns = [v for v in violations if v[2] == "WARN"]
        total_unsafe += len(unsafe)
        total_warn += len(warns)

        print(f"\n{'=' * 60}")
        print(f"Migration: {migration_file.name}")
        for line_text, description, severity in violations:
            marker = "🚫 UNSAFE" if severity == "UNSAFE" else "⚠️  WARN"
            print(f"  {marker}: {description}")
            print(f"    Code: {line_text}")

    print(f"\n{'=' * 60}")
    print(f"Summary: {len(migration_files)} migrations checked")
    print(f"  UNSAFE: {total_unsafe}  WARN: {total_warn}")

    if total_unsafe > 0:
        print("\n[FAIL] Deploy blocked — fix UNSAFE migrations before proceeding.")
        print("       See docs/ARCHITECTURE.md §zero-downtime-migrations for guidance.")
        return 1

    if total_warn > 0:
        print("\n[PASS with warnings] Review WARN items before deploying to production.")
        return 0

    print("\n[PASS] All migrations are zero-downtime safe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
