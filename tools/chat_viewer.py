#!/usr/bin/env python
import argparse
import json
import mimetypes
import os
import shutil
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = (PROJECT_ROOT / "TEST").resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from tools.safe_export import contact_kind, contact_matches, display_name, normalize_export_time, resolve_safe_db_dir
from wxManager import DatabaseConnection, MessageType
from wxManager.model import Me
from wxManager.decrypt.decrypt_dat import decode_dat


KIND_LABELS = {
    "person": "联系人",
    "group": "群聊",
    "public": "公众号",
    "openim": "OpenIM",
}


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>WeChatMsg Viewer</title>
  <style>
    :root { color-scheme: light; font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif; }
    body { margin: 0; background: #f5f7f8; color: #1f2933; }
    .app { display: grid; grid-template-columns: 320px 1fr; height: 100vh; }
    aside { border-right: 1px solid #d8dee4; background: #fff; display: flex; flex-direction: column; min-width: 0; }
    main { display: flex; flex-direction: column; min-width: 0; }
    header { padding: 12px; border-bottom: 1px solid #d8dee4; background: #fff; display: flex; gap: 8px; align-items: center; }
    input, select, button { font: inherit; border: 1px solid #c9d1d9; border-radius: 6px; padding: 7px 9px; background: #fff; }
    button { cursor: pointer; background: #f6f8fa; }
    button:hover { background: #eef2f5; }
    .search { display: grid; gap: 8px; padding: 12px; border-bottom: 1px solid #e5e9ee; }
    .row { display: flex; gap: 8px; }
    .row > * { min-width: 0; }
    .row input { flex: 1; }
    .conversations { overflow: auto; }
    .conv { padding: 10px 12px; border-bottom: 1px solid #eef1f4; cursor: pointer; }
    .conv:hover, .conv.active { background: #edf6ff; }
    .conv-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .conv-meta, .summary { color: #64748b; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 3px; }
    .messages { flex: 1; overflow: auto; padding: 18px 24px; }
    .msg { display: flex; margin: 10px 0; gap: 8px; align-items: flex-start; }
    .msg.self { justify-content: flex-end; }
    .bubble { max-width: min(680px, 78%); background: #fff; border: 1px solid #dfe5ea; border-radius: 8px; padding: 8px 10px; box-shadow: 0 1px 2px rgba(15,23,42,.04); }
    .self .bubble { background: #dff7c8; border-color: #c9eeb0; }
    .sender { color: #57606a; font-size: 12px; margin-bottom: 4px; }
    .time { text-align: center; color: #7b8794; font-size: 12px; margin: 16px 0 8px; }
    .text { white-space: pre-wrap; line-height: 1.5; word-break: break-word; }
    .media-img, .emoji { max-width: 280px; max-height: 320px; border-radius: 6px; display: block; }
    audio { width: 260px; max-width: 100%; }
    .link { display: grid; grid-template-columns: 1fr 72px; gap: 10px; min-width: 260px; color: inherit; text-decoration: none; }
    .link-title { font-weight: 600; line-height: 1.35; }
    .link-desc { color: #57606a; font-size: 13px; margin-top: 5px; line-height: 1.35; }
    .link img { width: 72px; height: 72px; object-fit: cover; border-radius: 6px; background: #edf2f7; }
    .placeholder { color: #64748b; font-size: 13px; }
    .toolbar { flex-wrap: wrap; }
    .toolbar input { width: 145px; }
    .empty { padding: 24px; color: #64748b; }
    @media (max-width: 800px) {
      .app { grid-template-columns: 1fr; }
      aside { height: 40vh; border-right: 0; border-bottom: 1px solid #d8dee4; }
      main { height: 60vh; }
      .messages { padding: 12px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="search">
        <div class="row">
          <input id="convQuery" placeholder="搜索联系人/群聊/wxid" />
          <button id="reload">刷新</button>
        </div>
        <div class="row">
          <select id="kind">
            <option value="all">全部</option>
            <option value="person">联系人</option>
            <option value="group">群聊</option>
            <option value="public">公众号</option>
            <option value="openim">OpenIM</option>
          </select>
          <input id="convLimit" type="number" min="1" value="200" title="会话数量" />
        </div>
      </div>
      <div id="conversations" class="conversations"></div>
    </aside>
    <main>
      <header class="toolbar">
        <strong id="title">选择一个会话</strong>
        <input id="fromDate" placeholder="开始日期 YYYY-MM-DD" />
        <input id="toDate" placeholder="结束日期 YYYY-MM-DD" />
        <input id="msgLimit" type="number" min="1" value="300" title="消息数量" />
        <button id="loadMessages">读取</button>
      </header>
      <div id="messages" class="messages"><div class="empty">从左侧选择联系人或群聊。</div></div>
    </main>
  </div>
  <script>
    let activeWxid = "";
    let activeName = "";

    const $ = (id) => document.getElementById(id);

    function setText(el, text) { el.textContent = text || ""; }

    async function fetchJson(url) {
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }

    async function loadConversations() {
      const params = new URLSearchParams({
        query: $("convQuery").value,
        kind: $("kind").value,
        limit: $("convLimit").value || "200",
      });
      const data = await fetchJson(`/api/conversations?${params}`);
      const box = $("conversations");
      box.innerHTML = "";
      if (!data.items.length) {
        box.innerHTML = '<div class="empty">没有匹配的会话。</div>';
        return;
      }
      for (const item of data.items) {
        const div = document.createElement("div");
        div.className = "conv" + (item.wxid === activeWxid ? " active" : "");
        div.onclick = () => {
          activeWxid = item.wxid;
          activeName = item.name;
          $("title").textContent = `${item.name} (${item.kind_label || item.kind})`;
          for (const el of document.querySelectorAll(".conv")) el.classList.remove("active");
          div.classList.add("active");
          loadMessages();
        };
        const name = document.createElement("div");
        name.className = "conv-name";
        setText(name, item.name);
        const meta = document.createElement("div");
        meta.className = "conv-meta";
        setText(meta, `${item.kind_label || item.kind}  ${item.wxid}`);
        const summary = document.createElement("div");
        summary.className = "summary";
        setText(summary, item.summary || "");
        div.append(name, meta, summary);
        box.appendChild(div);
      }
    }

    function renderMessage(msg) {
      const wrap = document.createElement("div");
      wrap.className = "msg" + (msg.is_sender ? " self" : "");
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      if (msg.is_chatroom && !msg.is_sender) {
        const sender = document.createElement("div");
        sender.className = "sender";
        setText(sender, msg.display_name || msg.sender_id);
        bubble.appendChild(sender);
      }

      if (msg.kind === "text" || msg.kind === "unknown" || msg.kind === "system") {
        const text = document.createElement("div");
        text.className = "text";
        setText(text, msg.text || msg.type_name || "");
        bubble.appendChild(text);
      } else if (msg.kind === "image" && msg.media_url) {
        const img = document.createElement("img");
        img.className = "media-img";
        img.src = msg.media_url;
        img.loading = "lazy";
        bubble.appendChild(img);
      } else if (msg.kind === "emoji") {
        if (msg.media_url) {
          const img = document.createElement("img");
          img.className = "emoji";
          img.src = msg.media_url;
          img.loading = "lazy";
          bubble.appendChild(img);
        }
        const desc = document.createElement("div");
        desc.className = "placeholder";
        setText(desc, msg.description || "表情");
        bubble.appendChild(desc);
      } else if (msg.kind === "audio") {
        if (msg.media_url) {
          const audio = document.createElement("audio");
          audio.controls = true;
          audio.src = msg.media_url;
          bubble.appendChild(audio);
        }
        const text = document.createElement("div");
        text.className = "placeholder";
        setText(text, msg.voice_to_text || `语音 ${msg.duration || ""}`);
        bubble.appendChild(text);
      } else if (msg.kind === "link") {
        const a = document.createElement("a");
        a.className = "link";
        a.href = msg.url || "#";
        a.target = "_blank";
        a.rel = "noreferrer";
        const info = document.createElement("div");
        const title = document.createElement("div");
        title.className = "link-title";
        setText(title, msg.title || "链接");
        const desc = document.createElement("div");
        desc.className = "link-desc";
        setText(desc, msg.description || msg.app_name || msg.url || "");
        info.append(title, desc);
        a.appendChild(info);
        if (msg.cover_url) {
          const img = document.createElement("img");
          img.src = msg.cover_url;
          img.loading = "lazy";
          a.appendChild(img);
        }
        bubble.appendChild(a);
      } else if (msg.kind === "video" && msg.media_url) {
        const video = document.createElement("video");
        video.controls = true;
        video.src = msg.media_url;
        video.style.maxWidth = "320px";
        bubble.appendChild(video);
      } else {
        const text = document.createElement("div");
        text.className = "text";
        setText(text, msg.text || msg.type_name || "暂不支持的消息");
        bubble.appendChild(text);
      }
      wrap.appendChild(bubble);
      return wrap;
    }

    async function loadMessages() {
      if (!activeWxid) return;
      const params = new URLSearchParams({
        wxid: activeWxid,
        from_date: $("fromDate").value,
        to_date: $("toDate").value,
        limit: $("msgLimit").value || "300",
      });
      const data = await fetchJson(`/api/messages?${params}`);
      const box = $("messages");
      box.innerHTML = "";
      let lastDate = "";
      for (const msg of data.items) {
        const date = (msg.time || "").slice(0, 10);
        if (date && date !== lastDate) {
          const sep = document.createElement("div");
          sep.className = "time";
          setText(sep, date);
          box.appendChild(sep);
          lastDate = date;
        }
        box.appendChild(renderMessage(msg));
      }
      if (!data.items.length) box.innerHTML = '<div class="empty">这个范围内没有消息。</div>';
      box.scrollTop = box.scrollHeight;
    }

    $("reload").onclick = loadConversations;
    $("loadMessages").onclick = loadMessages;
    $("convQuery").addEventListener("keydown", (e) => { if (e.key === "Enter") loadConversations(); });
    loadConversations().catch((err) => $("conversations").innerHTML = `<div class="empty">${err}</div>`);
  </script>
</body>
</html>"""


def require_inside_test(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(TEST_ROOT)
    except ValueError as exc:
        raise SystemExit(f"{label} must be under TEST: {resolved}") from exc
    return resolved


def to_time_range(from_date: str, to_date: str, default_days: int):
    if from_date:
        start = normalize_export_time(from_date, "from-date")
    else:
        start = (datetime.now() - timedelta(days=default_days)).strftime("%Y-%m-%d 00:00:00")
    if to_date:
        end = normalize_export_time(to_date, "to-date")
    else:
        end = "2035-12-31 23:59:59"
    return [start, end]


def safe_name(value: str) -> str:
    allowed = []
    for char in value:
        if char.isalnum() or char in ("-", "_", "."):
            allowed.append(char)
        else:
            allowed.append("_")
    return "".join(allowed).strip("._") or "item"


def fallback_contact_item(wxid: str, session=None):
    kind = contact_kind(type("ContactStub", (), {"wxid": wxid})())
    return {
        "wxid": wxid,
        "name": wxid,
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, kind),
        "summary": session[5] if session and len(session) > 5 else "",
        "last_timestamp": session[4] if session and len(session) > 4 else 0,
    }


class ViewerState:
    def __init__(self, db_dir: Path, db_version: int, cache_dir: Path, default_days: int):
        self.db_dir = db_dir
        self.db_version = db_version
        self.cache_dir = cache_dir
        self.default_days = default_days
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.asset_root = self.cache_dir / "assets"
        self.asset_root.mkdir(parents=True, exist_ok=True)
        conn = DatabaseConnection(str(db_dir), db_version)
        self.database = conn.get_interface()
        if self.database is None:
            raise SystemExit("Failed to open copied database directory.")

    def contact_to_item(self, contact, session=None):
        wxid = getattr(contact, "wxid", "")
        kind = contact_kind(contact)
        return {
            "wxid": wxid,
            "name": display_name(contact),
            "kind": kind,
            "kind_label": KIND_LABELS.get(kind, kind),
            "summary": session[5] if session and len(session) > 5 else "",
            "last_timestamp": session[4] if session and len(session) > 4 else 0,
        }

    def conversations(self, kind: str, query: str, limit: int):
        seen = set()
        items = []
        sessions = self.database.get_session() or []
        for session in sessions:
            wxid = session[0]
            contact = self.database.get_contact_by_username(wxid)
            if not contact:
                fallback = fallback_contact_item(wxid, session)
                if kind != "all" and fallback["kind"] != kind:
                    continue
                if query and query.casefold().strip() not in wxid.casefold():
                    continue
                items.append(fallback)
                seen.add(wxid)
                if limit and len(items) >= limit:
                    return items
                continue
            if not contact_matches(contact, kind, query):
                continue
            items.append(self.contact_to_item(contact, session))
            seen.add(wxid)
            if limit and len(items) >= limit:
                return items
        for contact in self.database.get_contacts():
            wxid = getattr(contact, "wxid", "")
            if wxid in seen or not contact_matches(contact, kind, query):
                continue
            items.append(self.contact_to_item(contact))
            if limit and len(items) >= limit:
                break
        return items

    def asset_url(self, path: Path) -> str:
        rel = path.resolve().relative_to(self.asset_root.resolve())
        return "/assets/" + quote(str(rel).replace("\\", "/"))

    def source_file(self, relative_path: str) -> Path | None:
        if not relative_path:
            return None
        src = (Path(Me().wx_dir) / relative_path).resolve()
        try:
            src.relative_to(Path(Me().wx_dir).resolve())
        except ValueError:
            return None
        return src if src.exists() and src.is_file() else None

    def copy_source_asset(self, source: Path, subdir: str, name: str) -> str:
        target_dir = self.asset_root / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix or ".bin"
        target = target_dir / f"{safe_name(name)}{suffix}"
        if not target.exists():
            shutil.copy2(source, target)
        return self.asset_url(target)

    def image_url(self, message, thumb=False) -> str:
        rel_path = getattr(message, "thumb_path" if thumb else "path", "") or getattr(message, "path", "")
        source = self.source_file(rel_path)
        if not source:
            return ""
        if source.suffix.lower() == ".dat":
            out_dir = self.asset_root / "image"
            out_dir.mkdir(parents=True, exist_ok=True)
            decoded = decode_dat(int(Me().xor_key or 0), str(source), str(out_dir), f"{message.server_id}_{'t' if thumb else 'i'}")
            return self.asset_url(Path(decoded)) if decoded else ""
        return self.copy_source_asset(source, "image", f"{message.server_id}_{'t' if thumb else 'i'}")

    def video_url(self, message) -> str:
        source = self.source_file(getattr(message, "path", ""))
        if not source:
            return ""
        return self.copy_source_asset(source, "video", str(message.server_id))

    def audio_url(self, message) -> str:
        out_dir = self.asset_root / "voice"
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            path = self.database.get_audio(message.server_id, str(out_dir), str(message.server_id))
        except Exception:
            return ""
        return self.asset_url(Path(path)) if path and Path(path).exists() else ""

    def message_payload(self, message):
        payload = {
            "id": str(message.server_id),
            "time": message.str_time,
            "type": message.type,
            "type_name": message.type_name(),
            "is_sender": bool(message.is_sender),
            "is_chatroom": bool(message.is_chatroom()),
            "sender_id": message.sender_id,
            "display_name": message.display_name,
            "kind": "unknown",
            "text": message.to_text(),
        }
        if message.type in (MessageType.Text, MessageType.Text2, MessageType.Quote):
            payload["kind"] = "text"
        elif message.type == MessageType.System or message.type == MessageType.Pat:
            payload["kind"] = "system"
        elif message.type == MessageType.Image:
            payload["kind"] = "image"
            payload["media_url"] = self.image_url(message, thumb=False) or self.image_url(message, thumb=True)
        elif message.type == MessageType.Audio:
            payload["kind"] = "audio"
            payload["media_url"] = self.audio_url(message)
            payload["voice_to_text"] = getattr(message, "audio_text", "")
            payload["duration"] = getattr(message, "duration", 0)
        elif message.type == MessageType.Emoji:
            payload["kind"] = "emoji"
            payload["media_url"] = getattr(message, "url", "") or getattr(message, "thumb_url", "")
            payload["description"] = getattr(message, "description", "")
        elif message.type in (
            MessageType.LinkMessage,
            MessageType.LinkMessage2,
            MessageType.LinkMessage4,
            MessageType.LinkMessage5,
            MessageType.LinkMessage6,
            MessageType.Music,
            MessageType.Applet,
            MessageType.Applet2,
            MessageType.WeChatVideo,
        ):
            payload["kind"] = "link"
            payload["url"] = getattr(message, "href", "") or getattr(message, "url", "")
            payload["title"] = getattr(message, "title", "") or getattr(message, "description", "")
            payload["description"] = getattr(message, "description", "")
            payload["cover_url"] = getattr(message, "cover_url", "") or getattr(message, "thumb_url", "")
            payload["app_name"] = getattr(message, "app_name", "")
        elif message.type == MessageType.Video:
            payload["kind"] = "video"
            payload["media_url"] = self.video_url(message)
        elif message.type == MessageType.File:
            payload["kind"] = "file"
        return payload

    def messages(self, wxid: str, from_date: str, to_date: str, limit: int):
        time_range = to_time_range(from_date, to_date, self.default_days)
        messages = self.database.get_messages(wxid, time_range=time_range)
        messages.sort(key=lambda item: item.timestamp)
        if limit:
            messages = messages[-limit:]
        return [self.message_payload(message) for message in messages]


def json_response(handler: BaseHTTPRequestHandler, payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def text_response(handler: BaseHTTPRequestHandler, text: str, status=200, content_type="text/html; charset=utf-8"):
    data = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def make_handler(state: ViewerState):
    class ChatViewerHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/":
                    text_response(self, HTML)
                elif parsed.path == "/api/conversations":
                    params = parse_qs(parsed.query)
                    kind = params.get("kind", ["all"])[0]
                    query = params.get("query", [""])[0]
                    limit = int(params.get("limit", ["200"])[0] or "200")
                    json_response(self, {"items": state.conversations(kind, query, limit)})
                elif parsed.path == "/api/messages":
                    params = parse_qs(parsed.query)
                    wxid = params.get("wxid", [""])[0]
                    if not wxid:
                        json_response(self, {"error": "wxid is required"}, 400)
                        return
                    limit = int(params.get("limit", ["300"])[0] or "300")
                    from_date = params.get("from_date", [""])[0]
                    to_date = params.get("to_date", [""])[0]
                    json_response(self, {"items": state.messages(wxid, from_date, to_date, limit)})
                elif parsed.path.startswith("/assets/"):
                    rel = unquote(parsed.path[len("/assets/"):])
                    target = (state.asset_root / rel).resolve()
                    try:
                        target.relative_to(state.asset_root.resolve())
                    except ValueError:
                        text_response(self, "Forbidden", 403, "text/plain; charset=utf-8")
                        return
                    if not target.exists() or not target.is_file():
                        text_response(self, "Not found", 404, "text/plain; charset=utf-8")
                        return
                    mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                    data = target.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    text_response(self, "Not found", 404, "text/plain; charset=utf-8")
            except Exception as exc:
                json_response(self, {"error": str(exc)}, 500)

    return ChatViewerHandler


def main():
    parser = argparse.ArgumentParser(description="Start a local read-only WeChat chat viewer.")
    parser.add_argument("--db-dir", required=True, help="Copied decrypted database directory.")
    parser.add_argument("--db-version", type=int, choices=(3, 4), default=4)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cache-dir", default="TEST/viewer-cache", help="Media cache directory under TEST.")
    parser.add_argument("--days", type=int, default=30, help="Default message lookback window when no date is selected.")
    parser.add_argument("--open", action="store_true", help="Open the viewer in the default browser.")
    args = parser.parse_args()

    db_dir = resolve_safe_db_dir(args.db_dir)
    cache_dir = require_inside_test(Path(args.cache_dir), "Viewer cache directory")
    state = ViewerState(db_dir, args.db_version, cache_dir, args.days)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    url = f"http://{args.host}:{args.port}/"
    print(f"Chat viewer running at {url}")
    print("Press Ctrl+C to stop.")
    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
