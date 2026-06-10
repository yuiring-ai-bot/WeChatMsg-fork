#!/usr/bin/env python
import argparse
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


def main():
    parser = argparse.ArgumentParser(
        description="Safely export from a copied WeChatMsg database directory."
    )
    parser.add_argument("--db-dir", required=True, help="Copied decrypted database directory.")
    parser.add_argument("--db-version", type=int, choices=(3, 4), default=4)
    parser.add_argument("--wxid", required=True, help="Contact wxid to export.")
    parser.add_argument("--format", choices=("html", "markdown", "txt"), default="html")
    parser.add_argument("--output-dir", default="TEST/safe-output")
    parser.add_argument("--text-only", action="store_true", help="Export only text/link messages.")
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

    contact = database.get_contact_by_username(args.wxid)
    if not contact:
        raise SystemExit(f"Contact not found in copied database: {args.wxid}")

    exporter_class, file_type = exporters[args.format]
    message_types = None
    if args.text_only:
        message_types = {MessageType.Text, MessageType.Text2, MessageType.LinkMessage}

    exporter = exporter_class(
        database,
        contact,
        output_dir=str(output_dir),
        type_=file_type,
        message_types=message_types,
        time_range=["1970-01-01 00:00:00", "2035-12-31 23:59:59"],
        group_members=None,
    )
    exporter.start()
    print(f"Export completed: {output_dir}")


if __name__ == "__main__":
    main()
