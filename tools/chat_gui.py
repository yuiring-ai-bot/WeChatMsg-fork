#!/usr/bin/env python
import argparse
import os
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageTk

from tools.chat_viewer import ViewerState, require_inside_test
from tools.safe_export import resolve_safe_db_dir


KIND_OPTIONS = [
    ("all", "全部"),
    ("person", "联系人"),
    ("group", "群聊"),
    ("public", "公众号"),
    ("openim", "OpenIM"),
]


class ChatGui:
    def __init__(self, root: tk.Tk, state: ViewerState):
        self.root = root
        self.state = state
        self.conversations = []
        self.active = None
        self.image_refs = []

        root.title("WeChatMsg 本地聊天查看")
        root.geometry("1120x760")
        root.minsize(900, 560)

        self.kind_var = tk.StringVar(value="all")
        self.query_var = tk.StringVar()
        self.limit_var = tk.StringVar(value="200")
        self.from_var = tk.StringVar()
        self.to_var = tk.StringVar()
        self.msg_limit_var = tk.StringVar(value="300")
        self.title_var = tk.StringVar(value="选择一个会话")
        self.status_var = tk.StringVar(value="只读取 TEST 下的解密副本")

        self.build_layout()
        self.load_conversations()

    def build_layout(self):
        style = ttk.Style()
        style.configure("Meta.TLabel", foreground="#64748b", font=("Microsoft YaHei UI", 9))
        style.configure("Sender.TLabel", foreground="#57606a", font=("Microsoft YaHei UI", 9))
        style.configure("Bubble.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("SelfBubble.TFrame", background="#dff7c8", relief="solid", borderwidth=1)

        root_frame = ttk.Frame(self.root)
        root_frame.pack(fill=tk.BOTH, expand=True)

        panes = ttk.PanedWindow(root_frame, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(panes, width=330)
        right = ttk.Frame(panes)
        panes.add(left, weight=0)
        panes.add(right, weight=1)

        search = ttk.Frame(left, padding=10)
        search.pack(fill=tk.X)
        ttk.Entry(search, textvariable=self.query_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(search, text="刷新", command=self.load_conversations).pack(side=tk.LEFT, padx=(8, 0))

        filters = ttk.Frame(left, padding=(10, 0, 10, 10))
        filters.pack(fill=tk.X)
        self.kind_box = ttk.Combobox(
            filters,
            state="readonly",
            values=[label for _, label in KIND_OPTIONS],
            width=10,
        )
        self.kind_box.current(0)
        self.kind_box.pack(side=tk.LEFT)
        ttk.Label(filters, text="数量").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(filters, textvariable=self.limit_var, width=8).pack(side=tk.LEFT)

        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.conv_list = tk.Listbox(
            list_frame,
            activestyle="none",
            borderwidth=0,
            highlightthickness=0,
            font=("Microsoft YaHei UI", 10),
        )
        conv_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.conv_list.yview)
        self.conv_list.configure(yscrollcommand=conv_scroll.set)
        self.conv_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        conv_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.conv_list.bind("<<ListboxSelect>>", self.on_select_conversation)
        self.query_var.trace_add("write", lambda *_: self.root.after(300, self.load_conversations))

        toolbar = ttk.Frame(right, padding=10)
        toolbar.pack(fill=tk.X)
        ttk.Label(toolbar, textvariable=self.title_var, font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT)
        ttk.Label(toolbar, text="开始").pack(side=tk.LEFT, padx=(18, 4))
        ttk.Entry(toolbar, textvariable=self.from_var, width=13).pack(side=tk.LEFT)
        ttk.Label(toolbar, text="结束").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Entry(toolbar, textvariable=self.to_var, width=13).pack(side=tk.LEFT)
        ttk.Label(toolbar, text="数量").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Entry(toolbar, textvariable=self.msg_limit_var, width=7).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="读取", command=self.load_messages).pack(side=tk.LEFT, padx=(8, 0))

        body = ttk.Frame(right)
        body.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(body, background="#f5f7f8", borderwidth=0, highlightthickness=0)
        msg_scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=msg_scroll.set)
        self.messages_frame = ttk.Frame(self.canvas)
        self.messages_window = self.canvas.create_window((0, 0), window=self.messages_frame, anchor="nw")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        msg_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.messages_frame.bind("<Configure>", self.on_messages_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)

        status = ttk.Label(right, textvariable=self.status_var, anchor="w", padding=(10, 4), style="Meta.TLabel")
        status.pack(fill=tk.X)

    def selected_kind(self):
        label = self.kind_box.get()
        for value, item_label in KIND_OPTIONS:
            if item_label == label:
                return value
        return "all"

    def parse_limit(self, value: str, default: int):
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except ValueError:
            return default

    def load_conversations(self):
        try:
            items = self.state.conversations(
                self.selected_kind(),
                self.query_var.get(),
                self.parse_limit(self.limit_var.get(), 200),
            )
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))
            return
        current = self.active["wxid"] if self.active else ""
        self.conversations = items
        self.conv_list.delete(0, tk.END)
        active_index = None
        for index, item in enumerate(items):
            line = f"{item['name']}  [{item.get('kind_label', item['kind'])}]"
            if item.get("summary"):
                line += f"  {item['summary']}"
            self.conv_list.insert(tk.END, line)
            if item["wxid"] == current:
                active_index = index
        if active_index is not None:
            self.conv_list.selection_set(active_index)
        self.status_var.set(f"会话 {len(items)} 个")

    def on_select_conversation(self, _event=None):
        selection = self.conv_list.curselection()
        if not selection:
            return
        self.active = self.conversations[selection[0]]
        self.title_var.set(f"{self.active['name']} ({self.active.get('kind_label', self.active['kind'])})")
        self.load_messages()

    def clear_messages(self):
        self.image_refs.clear()
        for child in self.messages_frame.winfo_children():
            child.destroy()

    def load_messages(self):
        if not self.active:
            return
        self.clear_messages()
        try:
            items = self.state.messages(
                self.active["wxid"],
                self.from_var.get().strip(),
                self.to_var.get().strip(),
                self.parse_limit(self.msg_limit_var.get(), 300),
            )
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))
            return
        last_date = ""
        for message in items:
            date = (message.get("time") or "")[:10]
            if date and date != last_date:
                ttk.Label(
                    self.messages_frame,
                    text=date,
                    style="Meta.TLabel",
                    anchor="center",
                    padding=(0, 14, 0, 6),
                ).pack(fill=tk.X)
                last_date = date
            self.add_message(message)
        if not items:
            ttk.Label(self.messages_frame, text="这个范围内没有消息。", padding=20).pack(anchor="w")
        self.status_var.set(f"{self.active['name']}：{len(items)} 条消息")
        self.root.after(80, lambda: self.canvas.yview_moveto(1.0))

    def add_message(self, message):
        outer = ttk.Frame(self.messages_frame, padding=(12, 4))
        outer.pack(fill=tk.X, anchor="e" if message.get("is_sender") else "w")

        side = tk.RIGHT if message.get("is_sender") else tk.LEFT
        bubble_style = "SelfBubble.TFrame" if message.get("is_sender") else "Bubble.TFrame"
        bubble = ttk.Frame(outer, style=bubble_style, padding=8)
        bubble.pack(side=side, anchor="e" if message.get("is_sender") else "w", padx=(80, 0) if message.get("is_sender") else (0, 80))

        if message.get("is_chatroom") and not message.get("is_sender"):
            ttk.Label(
                bubble,
                text=message.get("display_name") or message.get("sender_id") or "",
                style="Sender.TLabel",
                background="#ffffff",
            ).pack(anchor="w")

        kind = message.get("kind")
        if kind in ("text", "system", "unknown"):
            self.add_wrapped_label(bubble, message.get("text") or message.get("type_name") or "")
        elif kind == "image":
            self.add_image_or_link(bubble, message.get("media_url"), "图片")
        elif kind == "emoji":
            if message.get("media_url"):
                self.add_image_or_link(bubble, message.get("media_url"), "表情")
            if message.get("description"):
                self.add_wrapped_label(bubble, message["description"], muted=True)
        elif kind == "audio":
            self.add_audio(bubble, message)
        elif kind == "link":
            self.add_link(bubble, message)
        elif kind == "video":
            self.add_file_button(bubble, message.get("media_url"), "打开视频")
        elif kind == "file":
            self.add_wrapped_label(bubble, message.get("text") or "文件消息")
        else:
            self.add_wrapped_label(bubble, message.get("text") or message.get("type_name") or "暂不支持的消息")

    def add_wrapped_label(self, parent, text, muted=False):
        ttk.Label(
            parent,
            text=text,
            wraplength=520,
            justify=tk.LEFT,
            foreground="#64748b" if muted else "#1f2933",
            background=parent.cget("style") == "SelfBubble.TFrame" and "#dff7c8" or "#ffffff",
        ).pack(anchor="w")

    def local_asset_path(self, url: str) -> Path | None:
        if not url or not url.startswith("/assets/"):
            return None
        target = (self.state.asset_root / unquote(url[len("/assets/"):])).resolve()
        try:
            target.relative_to(self.state.asset_root.resolve())
        except ValueError:
            return None
        return target if target.exists() and target.is_file() else None

    def add_image_or_link(self, parent, url: str, label: str):
        path = self.local_asset_path(url)
        if path:
            try:
                image = Image.open(path)
                image.thumbnail((320, 360))
                photo = ImageTk.PhotoImage(image)
                self.image_refs.append(photo)
                tk.Label(parent, image=photo, borderwidth=0).pack(anchor="w")
                return
            except Exception:
                pass
        if url:
            ttk.Button(parent, text=f"打开{label}", command=lambda: self.open_url_or_file(url)).pack(anchor="w")
        else:
            self.add_wrapped_label(parent, f"{label}不可用", muted=True)

    def add_audio(self, parent, message):
        text = message.get("voice_to_text") or f"语音 {message.get('duration') or ''}"
        self.add_wrapped_label(parent, text, muted=not bool(message.get("voice_to_text")))
        if message.get("media_url"):
            ttk.Button(parent, text="播放语音", command=lambda: self.open_url_or_file(message["media_url"])).pack(anchor="w", pady=(6, 0))

    def add_file_button(self, parent, url: str, label: str):
        if url:
            ttk.Button(parent, text=label, command=lambda: self.open_url_or_file(url)).pack(anchor="w")
        else:
            self.add_wrapped_label(parent, "资源不可用", muted=True)

    def add_link(self, parent, message):
        title = message.get("title") or "链接"
        desc = message.get("description") or message.get("app_name") or message.get("url") or ""
        self.add_wrapped_label(parent, title)
        if desc:
            self.add_wrapped_label(parent, desc, muted=True)
        if message.get("cover_url"):
            self.add_image_or_link(parent, message.get("cover_url"), "封面")
        if message.get("url"):
            ttk.Button(parent, text="打开链接", command=lambda: self.open_url_or_file(message["url"])).pack(anchor="w", pady=(6, 0))

    def open_url_or_file(self, url: str):
        path = self.local_asset_path(url)
        if path:
            os.startfile(path)
            return
        webbrowser.open(url)

    def on_messages_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.messages_window, width=event.width)

    def on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


def main():
    parser = argparse.ArgumentParser(description="Start a local desktop WeChat chat viewer.")
    parser.add_argument("--db-dir", required=True, help="Copied decrypted database directory.")
    parser.add_argument("--db-version", type=int, choices=(3, 4), default=4)
    parser.add_argument("--cache-dir", default="TEST/viewer-cache", help="Media cache directory under TEST.")
    parser.add_argument("--days", type=int, default=30, help="Default message lookback window when no date is selected.")
    args = parser.parse_args()

    db_dir = resolve_safe_db_dir(args.db_dir)
    cache_dir = require_inside_test(Path(args.cache_dir), "Viewer cache directory")
    state = ViewerState(db_dir, args.db_version, cache_dir, args.days)

    root = tk.Tk()
    ChatGui(root, state)
    root.mainloop()


if __name__ == "__main__":
    main()
