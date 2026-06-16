#!/usr/bin/env python
import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.safe_export import resolve_safe_db_dir


def display_name(contact) -> str:
    remark = (getattr(contact, "remark", "") or "").strip()
    nickname = (getattr(contact, "nickname", "") or "").strip()
    alias = (getattr(contact, "alias", "") or "").strip()
    return remark or nickname or alias or getattr(contact, "wxid", "")


def contact_kind(contact) -> str:
    wxid = getattr(contact, "wxid", "")
    if wxid.endswith("@chatroom"):
        return "group"
    if wxid.startswith("gh_"):
        return "public"
    if wxid.endswith("@openim"):
        return "openim"
    return "person"


def main():
    parser = argparse.ArgumentParser(description="List contacts from a copied/decrypted WeChat database directory.")
    parser.add_argument("--db-dir", required=True, help="Copied decrypted database directory.")
    parser.add_argument("--db-version", type=int, choices=(3, 4), default=4)
    parser.add_argument("--kind", choices=("all", "person", "group", "public", "openim"), default="all")
    parser.add_argument("--query", default="", help="Case-insensitive substring filter for wxid, remark, nickname, or alias.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum rows to print. 0 means no limit.")
    parser.add_argument("--format", choices=("table", "csv"), default="table")
    args = parser.parse_args()

    db_dir = resolve_safe_db_dir(args.db_dir)

    from wxManager import DatabaseConnection

    conn = DatabaseConnection(str(db_dir), args.db_version)
    database = conn.get_interface()
    if database is None:
        raise SystemExit("Failed to open copied database directory.")

    query = args.query.casefold().strip()
    rows = []
    for contact in database.get_contacts():
        wxid = getattr(contact, "wxid", "")
        kind = contact_kind(contact)
        if args.kind != "all" and kind != args.kind:
            continue
        name = display_name(contact)
        nickname = getattr(contact, "nickname", "") or ""
        remark = getattr(contact, "remark", "") or ""
        alias = getattr(contact, "alias", "") or ""
        haystack = "\n".join([wxid, name, nickname, remark, alias]).casefold()
        if query and query not in haystack:
            continue
        rows.append(
            {
                "kind": kind,
                "name": name,
                "wxid": wxid,
                "remark": remark,
                "nickname": nickname,
                "alias": alias,
            }
        )
        if args.limit and len(rows) >= args.limit:
            break

    if args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=["kind", "name", "wxid", "remark", "nickname", "alias"])
        writer.writeheader()
        writer.writerows(rows)
    else:
        print(f"{'kind':<8} {'name':<32} wxid")
        print("-" * 80)
        for row in rows:
            name = row["name"][:32]
            print(f"{row['kind']:<8} {name:<32} {row['wxid']}")
    print(f"Total: {len(rows)}", file=sys.stderr)


if __name__ == "__main__":
    main()
