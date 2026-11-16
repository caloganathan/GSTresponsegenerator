"""Admin CLI — create or reset a user without touching the running server.

Operates directly on the persisted user store (config.STATE_DIR/users.json),
so it works wherever that volume is reachable: a Render Shell session against
the live deployment, or locally against a dev database.

The first-run partner account is only ever created once, at the moment the
user store is empty — set ADMIN_EMAIL/ADMIN_PASSWORD before that boot, or you
get a generated password that is only visible in the deploy log. This CLI is
the escape hatch when that moment has already passed: create a new partner
account, or reset an existing one, on demand.

    python -m backend.cli create-admin --email you@firm.in --password ...
    python -m backend.cli reset-password --email you@firm.in --password ...
    python -m backend.cli list-users

It also carries the model doctor, which is not about users at all but belongs
to the same category of thing: something you need to run against a live
deployment from a shell.

    python -m backend.cli check-models [--suggest]

And one piece of housekeeping for the general council's stored conversations,
which changed shape when the exchange stopped being stored under the names of
its stages. The application reads the old shape without help; this rewrites
the files so that nothing else has to.

    python -m backend.cli migrate-conversations            # report only
    python -m backend.cli migrate-conversations --apply    # rewrite them
"""

import argparse
import getpass
import sys

from . import config, models_doctor, storage, users


def _read_password(explicit: str = "") -> str:
    if explicit:
        return explicit
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        sys.exit(1)
    return password


def cmd_create_admin(args) -> int:
    password = _read_password(args.password)
    try:
        user = users.create_user(
            args.email, password, name=args.name or "", role=args.role
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Created {user['role']} account: {user['email']}")
    if user.get("name"):
        print(f"  Name: {user['name']}")
    return 0


def cmd_reset_password(args) -> int:
    record = users.find_by_email(args.email)
    if record is None:
        print(f"Error: no user with email {args.email!r}. "
              f"Use create-admin to create one.", file=sys.stderr)
        return 1

    password = _read_password(args.password)
    try:
        users.update_user(record["id"], password=password)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Password reset for {args.email}.")
    return 0


def cmd_list_users(args) -> int:
    all_users = users.list_users()
    if not all_users:
        print("No users. Run create-admin to create the first partner account.")
        return 0

    width = max(len(u["email"]) for u in all_users)
    for user in all_users:
        status = "active" if user["active"] else "disabled"
        last = user["last_login"] or "never signed in"
        print(f"{user['email']:<{width}}  {user['role']:<8}  {status:<9}  {last}")
    return 0


def cmd_set_role(args) -> int:
    record = users.find_by_email(args.email)
    if record is None:
        print(f"Error: no user with email {args.email!r}.", file=sys.stderr)
        return 1
    try:
        user = users.update_user(record["id"], role=args.role)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"{user['email']} is now {user['role']}.")
    return 0


def cmd_check_models(args) -> int:
    return models_doctor.report(show_suggestions=args.suggest)


def cmd_migrate_conversations(args) -> int:
    """
    Report on, or rewrite, conversations still stored in the old shape.

    Reports by default. Rewriting stored records is the kind of thing that
    should be looked at before it is done, so it has to be asked for.
    """
    print(f"Conversations at: {config.DATA_DIR}")
    report = storage.migrate_conversations(dry_run=not args.apply)

    verb = "Rewrote" if args.apply else "Would rewrite"
    print(f"Examined {report['examined']} file(s): "
          f"{report['current']} already current, "
          f"{len(report['upgraded'])} in the old shape.")
    for name in report["upgraded"]:
        print(f"  {verb}: {name}")
    for name in report["unreadable"]:
        print(f"  Left alone (unreadable, or not a conversation): {name}")
    if report["upgraded"] and not args.apply:
        print("Nothing was written. Run again with --apply to rewrite them.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.cli",
        description="Create or reset users directly against the persisted store.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser(
        "create-admin", help="Create a new user (a partner account, by default)"
    )
    create.add_argument("--email", required=True)
    create.add_argument("--password", default="",
                        help="Omit to be prompted (recommended over the shell history)")
    create.add_argument("--name", default="")
    create.add_argument("--role", default="partner",
                        choices=["partner", "manager", "staff"])
    create.set_defaults(func=cmd_create_admin)

    reset = subparsers.add_parser(
        "reset-password", help="Reset an existing user's password"
    )
    reset.add_argument("--email", required=True)
    reset.add_argument("--password", default="")
    reset.set_defaults(func=cmd_reset_password)

    role = subparsers.add_parser("set-role", help="Change an existing user's role")
    role.add_argument("--email", required=True)
    role.add_argument("--role", required=True,
                      choices=["partner", "manager", "staff"])
    role.set_defaults(func=cmd_set_role)

    listing = subparsers.add_parser("list-users", help="List all users")
    listing.set_defaults(func=cmd_list_users)

    doctor = subparsers.add_parser(
        "check-models",
        help="Check every configured model ID against OpenRouter's catalogue",
    )
    doctor.add_argument(
        "--suggest", action="store_true",
        help="Also propose replacements for any slot that fails, and print "
             "paste-ready environment variables",
    )
    doctor.set_defaults(func=cmd_check_models)

    migrate = subparsers.add_parser(
        "migrate-conversations",
        help="Rewrite general-council conversations stored in the old shape",
    )
    migrate.add_argument(
        "--apply", action="store_true",
        help="Rewrite the files. Without this the command only reports.",
    )
    migrate.set_defaults(func=cmd_migrate_conversations)

    return parser


# Commands that do not touch the user store, and so must not print a banner
# about it — `check-models` needs no volume and is routinely run from a laptop,
# and `migrate-conversations` works on DATA_DIR and names it itself.
_STORE_FREE_COMMANDS = {"check-models", "migrate-conversations"}


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in _STORE_FREE_COMMANDS:
        print(f"Operating on user store at: {config.STATE_DIR}")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
