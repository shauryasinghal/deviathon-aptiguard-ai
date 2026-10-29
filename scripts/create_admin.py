"""Create the first administrator for a non-demo deployment.

    ADMIN_EMAIL=... ADMIN_NAME=... ORG_NAME=... ORG_SLUG=... python scripts/create_admin.py
The password is read from ADMIN_PASSWORD if set (e.g. injected by a secret manager), otherwise prompted without echo.
It is never printed or logged.
"""
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
if Path("/srv/backend").exists():  # inside the container image
    sys.path.insert(0, "/srv/backend")

from app.bootstrap import create_admin  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def main() -> int:
    email = os.environ.get("ADMIN_EMAIL") or input("Admin email: ")
    name = os.environ.get("ADMIN_NAME") or input("Admin full name: ")
    org_name = os.environ.get("ORG_NAME", "Integraminds")
    org_slug = os.environ.get("ORG_SLUG", "integraminds")
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password (min 12 chars): ")
    with SessionLocal() as db:
        try:
            u = create_admin(db, org_name, org_slug, email, name, password)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        db.commit()
        print(f"created administrator id={u.id} for organisation '{org_slug}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
