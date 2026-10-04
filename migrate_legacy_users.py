import argparse
import os
import sys

import psycopg2
from legacy_user_import import plan_import

POSTGRES_CONNECT_TIMEOUT = 10


def connection_options(prefix: str) -> dict[str, str | int]:
    required = ("HOST", "DB", "USER", "PASSWORD")
    missing = [f"{prefix}_{key}" for key in required if not os.getenv(f"{prefix}_{key}")]
    if missing:
        raise RuntimeError(f"Missing database settings: {', '.join(missing)}")

    return {
        "host": os.environ[f"{prefix}_HOST"],
        "port": int(os.getenv(f"{prefix}_PORT", "5432")),
        "dbname": os.environ[f"{prefix}_DB"],
        "user": os.environ[f"{prefix}_USER"],
        "password": os.environ[f"{prefix}_PASSWORD"],
        "connect_timeout": POSTGRES_CONNECT_TIMEOUT,
        "application_name": "registar-discord-user-migration",
    }


def load_legacy_rows(source) -> list[tuple[str, str | None]]:
    source.set_session(readonly=True)
    with source.cursor() as cursor:
        cursor.execute('SELECT "discordId", priv_email FROM users')
        return cursor.fetchall()


def migrate(apply_changes: bool) -> int:
    source = None
    destination = None
    try:
        source = psycopg2.connect(**connection_options("OLD_POSTGRES"))
        destination = psycopg2.connect(**connection_options("REGISTAR_POSTGRES"))
        legacy_rows = load_legacy_rows(source)
        with destination:
            with destination.cursor() as cursor:
                cursor.execute(
                    'SELECT id, "discordId", "privateEmail", "ksetEmail" FROM "Member"'
                )
                member_rows = cursor.fetchall()
                plan, counts = plan_import(legacy_rows, member_rows)

                if apply_changes:
                    for discord_id, member_id, private_match, kset_match in plan:
                        cursor.execute(
                            """
                            UPDATE "Member"
                            SET "discordId" = %s,
                                "privateEmailVerified" =
                                    "privateEmailVerified" OR %s,
                                "ksetEmailVerified" =
                                    "ksetEmailVerified" OR %s,
                                "updatedAt" = CURRENT_TIMESTAMP
                            WHERE id = %s
                              AND ("discordId" IS NULL OR "discordId" = %s)
                            """,
                            (discord_id, private_match, kset_match, member_id, discord_id),
                        )
                        if cursor.rowcount != 1:
                            raise RuntimeError(
                                "A member changed during import; transaction rolled back."
                            )

        print(f"Mode: {'APPLY' if apply_changes else 'DRY RUN'}")
        print(f"Legacy rows: {len(legacy_rows)}")
        for status in (
            "would_link",
            "already_linked",
            "unmatched",
            "ambiguous_email",
            "discord_conflicts",
            "member_conflicts",
            "invalid",
        ):
            print(f"{status}: {counts[status]}")
        if not apply_changes:
            print("No data was written. Re-run with --apply to import safe matches.")
        return 0
    finally:
        if source is not None:
            source.close()
        if destination is not None:
            destination.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely copy old Discord ID/email links to Registar Member rows."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply safe matches. The legacy database remains read-only and unchanged.",
    )
    args = parser.parse_args()

    try:
        return migrate(apply_changes=args.apply)
    except (psycopg2.Error, RuntimeError, ValueError) as error:
        print(f"Migration failed: {type(error).__name__}. No source data was changed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
