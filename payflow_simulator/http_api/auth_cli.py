"""Manage Command Center accounts without accepting credentials from shell arguments."""
from __future__ import annotations

import argparse
import getpass
import json

from .config import load_settings
from .security import AuthStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=("admin", "responder", "viewer"), default="admin")
    update = sub.add_parser("update-user")
    update.add_argument("--user-id", required=True)
    update.add_argument("--role", choices=("admin", "responder", "viewer"))
    update.add_argument("--disable", action="store_true")
    sub.add_parser("list-users")
    args = parser.parse_args()
    store = AuthStore(load_settings().database_path)
    if args.action == "create-user":
        password = getpass.getpass("New password (12+ characters): ")
        if password != getpass.getpass("Confirm password: "):
            parser.error("passwords do not match")
        user = store.create_user(args.username, password, args.role)
        user.pop("password_hash", None)
        print(json.dumps(user, indent=2))
    elif args.action == "update-user":
        if args.role is None and not args.disable:
            parser.error("set --role or --disable")
        user = store.set_user(args.user_id, role=args.role, active=False if args.disable else None)
        print(json.dumps(user, indent=2))
    else:
        print(json.dumps(store.list_users(), indent=2))


if __name__ == "__main__":
    main()
