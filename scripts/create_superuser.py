"""Create or promote an admin-panel superuser.

The admin panel (`/admin`) only accepts active superusers. API registration
never grants that flag, so bootstrap the first admin with this script:

    uv run python scripts/create_superuser.py --email admin@example.com
    docker compose exec api uv run python scripts/create_superuser.py \\
        --email admin@example.com --password 'change-me-please'

Running it for an existing user promotes that account (and resets the
password when `--password` is supplied).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlmodel import select

from app.core.db_sync import session_scope
from app.core.security import hash_password
from app.models import User


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or promote a TeamFlow admin-panel superuser."
    )
    parser.add_argument("--email", required=True, help="Login email for the admin.")
    parser.add_argument(
        "--password",
        default=None,
        help="Required when creating a new user; optional password reset otherwise.",
    )
    parser.add_argument("--name", default="TeamFlow Admin", help="Full name.")
    args = parser.parse_args()

    email = args.email.strip().lower()
    with session_scope() as session:
        user = (
            session.execute(select(User).where(User.email == email))
            .scalar_one_or_none()
        )
        if user is None:
            if not args.password:
                print(
                    "error: --password is required when creating a new user",
                    file=sys.stderr,
                )
                return 2
            user = User(
                email=email,
                full_name=args.name,
                hashed_password=hash_password(args.password),
                is_superuser=True,
            )
            session.add(user)
            action = "created"
        else:
            user.is_superuser = True
            user.is_active = True
            if args.password:
                user.hashed_password = hash_password(args.password)
            action = "promoted"

    print(f"Superuser {action}: {email}")
    print("Log in at /admin with this email and password.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
