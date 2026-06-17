#!/usr/bin/env python
import argparse
from datetime import datetime
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


REAL_WECHAT_MARKERS = (
    "wechat files",
    "xwechat_files",
    "\\tencent\\wechat\\",
    "\\weixin\\",
)

def resolve_safe_db_dir(raw_path: str) -> Path:
    db_dir = Path(raw_path).expanduser().resolve()
    normalized = str(db_dir).lower()
    if any(marker in normalized for marker in REAL_WECHAT_MARKERS):
        raise SystemExit(
            "Refusing to use a real WeChat data directory. "
            "Copy the decrypted database folder to TEST/safe-db first."
        )
    if not db_dir.exists() or not db_dir.is_dir():
        raise SystemExit(f"Database directory does not exist: {db_dir}")
    return db_dir


def normalize_export_time(value: str, label: str) -> str:
    try:
        if len(value) == 10:
            datetime.strptime(value, "%Y-%m-%d")
            suffix = "00:00:00" if label == "from-date" else "23:59:59"
            return f"{value} {suffix}"
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value
    except ValueError as exc:
        raise SystemExit(f"--{label} must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS: {value}") from exc


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


def contact_matches(contact, kind: str, query: str) -> bool:
    actual_kind = contact_kind(contact)
    if kind != "all" and actual_kind != kind:
        return False
    query = query.casefold().strip()
    if not query:
        return True
    wxid = getattr(contact, "wxid", "") or ""
    nickname = getattr(contact, "nickname", "") or ""
    remark = getattr(contact, "remark", "") or ""
    alias = getattr(contact, "alias", "") or ""
    haystack = "\n".join([wxid, display_name(contact), nickname, remark, alias]).casefold()
    return query in haystack


def select_export_contacts(database, wxid: str, export_all: bool, kind: str, query: str, limit: int):
    if wxid and export_all:
        raise SystemExit("Use either --wxid for one contact or --all for batch export, not both.")
    if not wxid and not export_all:
        raise SystemExit("Specify --wxid for one contact, or pass --all to export matched contacts.")

    if wxid:
        contact = database.get_contact_by_username(wxid)
        if not contact:
            raise SystemExit(f"Contact not found in copied database: {wxid}")
        return [contact]

    contacts = []
    for contact in database.get_contacts():
        if not contact_matches(contact, kind, query):
            continue
        contacts.append(contact)
        if limit and len(contacts) >= limit:
            break
    if not contacts:
        raise SystemExit("No contacts matched the batch export filters.")
    return contacts


def main():
    parser = argparse.ArgumentParser(
        description="Safely export from a copied WeChatMsg database directory."
    )
    parser.add_argument("--db-dir", required=True, help="Copied decrypted database directory.")
    parser.add_argument("--db-version", type=int, choices=(3, 4), default=4)
    parser.add_argument("--wxid", default="", help="Contact wxid to export. Omit only when using --all.")
    parser.add_argument("--all", action="store_true", help="Export all contacts matched by --kind/--query/--limit.")
    parser.add_argument("--kind", choices=("all", "person", "group", "public", "openim"), default="all")
    parser.add_argument("--query", default="", help="Batch export substring filter for wxid, remark, nickname, or alias.")
    parser.add_argument("--limit", type=int, default=0, help="Batch export maximum contact count. 0 means no limit.")
    parser.add_argument("--format", choices=("html", "markdown", "txt"), default="html")
    parser.add_argument("--output-dir", default="TEST/safe-output")
    parser.add_argument("--text-only", action="store_true", help="Export only text/link messages.")
    parser.add_argument("--from-date", default="1971-01-01", help="Start date/time, YYYY-MM-DD or YYYY-MM-DD HH:MM:SS.")
    parser.add_argument("--to-date", default="2035-12-31", help="End date/time, YYYY-MM-DD or YYYY-MM-DD HH:MM:SS.")
    args = parser.parse_args()

    db_dir = resolve_safe_db_dir(args.db_dir)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    from exporter.config import FileType
    from exporter import HtmlExporter, TxtExporter, MarkdownExporter
    from wxManager import DatabaseConnection, MessageType

    exporters = {
        "html": (HtmlExporter, FileType.HTML),
        "txt": (TxtExporter, FileType.TXT),
        "markdown": (MarkdownExporter, FileType.MARKDOWN),
    }

    conn = DatabaseConnection(str(db_dir), args.db_version)
    database = conn.get_interface()
    if database is None:
        raise SystemExit("Failed to open copied database directory.")

    exporter_class, file_type = exporters[args.format]
    message_types = None
    if args.text_only:
        message_types = {MessageType.Text, MessageType.Text2, MessageType.LinkMessage}

    from_time = normalize_export_time(args.from_date, "from-date")
    to_time = normalize_export_time(args.to_date, "to-date")
    if from_time > to_time:
        raise SystemExit("--from-date must not be later than --to-date.")

    contacts = select_export_contacts(database, args.wxid, args.all, args.kind, args.query, args.limit)
    print(f"Exporting {len(contacts)} contact(s).")
    failed = []
    for index, contact in enumerate(contacts, start=1):
        wxid = getattr(contact, "wxid", "")
        print(f"[{index}/{len(contacts)}] {display_name(contact)} ({wxid})")
        try:
            exporter = exporter_class(
                database,
                contact,
                output_dir=str(output_dir),
                type_=file_type,
                message_types=message_types,
                time_range=[from_time, to_time],
                group_members=None,
            )
            exporter.start()
        except Exception as exc:
            failed.append((wxid, str(exc)))
            print(f"  failed: {exc}", file=sys.stderr)

    if failed:
        print("Batch export completed with failures:", file=sys.stderr)
        for wxid, error in failed:
            print(f"- {wxid}: {error}", file=sys.stderr)
        raise SystemExit(1)

    print(f"Export completed: {output_dir}")


if __name__ == "__main__":
    main()
