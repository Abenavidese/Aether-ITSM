"""
Applies (or rolls back) Postgres Row-Level Security — roadmap 2.5.

    .venv/Scripts/python.exe scripts/apply_rls.py                 # DATABASE_URL from .env
    .venv/Scripts/python.exe scripts/apply_rls.py --rollback
    .venv/Scripts/python.exe scripts/apply_rls.py --database-url postgresql://...

Both scripts are idempotent. After enabling, set DB_RLS_ENABLED=true so
tenant-scoped sessions switch to the aether_tenant role; before rolling
back, set it to false first (see src/db/tenant_scope.py).
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine  # noqa: E402

RLS_DIR = PROJECT_ROOT / "src" / "db" / "rls"


def apply(database_url: str, rollback: bool = False) -> None:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if not database_url.startswith("postgresql"):
        raise SystemExit("RLS is a Postgres feature; DATABASE_URL is not Postgres.")
    sql = (RLS_DIR / ("disable.sql" if rollback else "enable.sql")).read_text(encoding="utf-8")
    engine = create_engine(database_url)
    raw = engine.raw_connection()
    try:
        # Raw DBAPI cursor, no parameters: the script's format('... %I') must
        # reach Postgres verbatim, not be read as driver placeholders.
        with raw.cursor() as cursor:
            cursor.execute(sql)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    url = args.database_url
    if not url:
        from src.config import get_settings
        url = os.environ.get("DATABASE_URL") or get_settings().database_url
    apply(url, rollback=args.rollback)
    print("RLS rolled back." if args.rollback else "RLS enabled. Now set DB_RLS_ENABLED=true.")


if __name__ == "__main__":
    main()
