"""Operator CLI:  python -m app.cli create-admin admin@example.com"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models import User
from app.security import passwords
from app.services import audit, ledger


def create_admin(email: str) -> int:
    init_db()
    pw = getpass.getpass("Password: ")
    errors = passwords.validate_password_policy(pw, email=email)
    if errors:
        print("Weak password: " + "; ".join(errors), file=sys.stderr)
        return 1
    with SessionLocal() as db:
        if db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none():
            print("User already exists", file=sys.stderr)
            return 1
        user = User(email=email.lower(), password_hash=passwords.hash_password(pw),
                    full_name="Administrator", role="admin")
        db.add(user)
        db.flush()
        ledger.open_account(db, user)
        audit.record(db, "admin.created", actor_user_id=user.id, details={"via": "cli"})
        db.commit()
    print("Admin created. Enable MFA right after first login.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="vaultpay")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-admin")
    p.add_argument("email")
    args = parser.parse_args()
    return create_admin(args.email)


if __name__ == "__main__":
    raise SystemExit(main())
