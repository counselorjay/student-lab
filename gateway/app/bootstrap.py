"""One-shot bootstrap CLI.

Usage:
    python -m app.bootstrap admin <email> [--name "Display Name"]
    python -m app.bootstrap mintkey <user_id> [--label laptop]
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime

from sqlalchemy import select

from .auth import make_api_key
from .config import get_settings
from .db import init_engine, session_scope
from .models import ApiKey, User


def cmd_admin(email: str, name: str) -> int:
    settings = get_settings()
    init_engine()
    email_l = email.strip().lower()
    with session_scope() as db:
        user = db.execute(select(User).where(User.email == email_l)).scalar_one_or_none()
        if user is None:
            user = User(
                id=str(uuid.uuid4()),
                email=email_l,
                name=name,
                daily_request_limit=settings.default_daily_request_limit,
                daily_token_limit=settings.default_daily_token_limit,
            )
            db.add(user)
            db.flush()
            print(f"Created user {user.id} ({email_l}).")
        else:
            print(f"User {user.id} ({email_l}) already exists.")

        full, prefix, hashed = make_api_key()
        key = ApiKey(
            id=str(uuid.uuid4()),
            user_id=user.id,
            key_prefix=prefix,
            key_hash=hashed,
            label="bootstrap",
        )
        db.add(key)

        if email_l != settings.admin_email.strip().lower():
            print(
                f"Note: ADMIN_EMAIL is {settings.admin_email}, not {email_l}. "
                "This user will not pass require_admin until ADMIN_EMAIL matches."
            )

    print()
    print("API KEY (shown once, save it now):")
    print(f"  {full}")
    print()
    print(f"Prefix: {prefix}")
    return 0


def cmd_mintkey(user_id: str, label: str) -> int:
    init_engine()
    with session_scope() as db:
        user = db.get(User, user_id)
        if user is None:
            print(f"No user with id {user_id}", file=sys.stderr)
            return 1
        full, prefix, hashed = make_api_key()
        key = ApiKey(
            id=str(uuid.uuid4()),
            user_id=user.id,
            key_prefix=prefix,
            key_hash=hashed,
            label=label,
        )
        db.add(key)
    print(f"API KEY for {user.email} ({label}):")
    print(f"  {full}")
    return 0


def cmd_revoke(key_prefix: str) -> int:
    init_engine()
    with session_scope() as db:
        rows = db.execute(select(ApiKey).where(ApiKey.key_prefix == key_prefix)).scalars().all()
        if not rows:
            print(f"No keys matching prefix {key_prefix}", file=sys.stderr)
            return 1
        for r in rows:
            r.revoked_at = datetime.utcnow()
        print(f"Revoked {len(rows)} key(s) with prefix {key_prefix}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.bootstrap")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_admin = sub.add_parser("admin", help="Create or look up a user, mint a key.")
    p_admin.add_argument("email")
    p_admin.add_argument("--name", default="Admin")

    p_mint = sub.add_parser("mintkey", help="Mint a new key for an existing user.")
    p_mint.add_argument("user_id")
    p_mint.add_argument("--label", default="cli")

    p_rev = sub.add_parser("revoke", help="Revoke all keys with a given prefix.")
    p_rev.add_argument("key_prefix")

    args = p.parse_args(argv)
    if args.cmd == "admin":
        return cmd_admin(args.email, args.name)
    if args.cmd == "mintkey":
        return cmd_mintkey(args.user_id, args.label)
    if args.cmd == "revoke":
        return cmd_revoke(args.key_prefix)
    return 2


if __name__ == "__main__":
    sys.exit(main())
