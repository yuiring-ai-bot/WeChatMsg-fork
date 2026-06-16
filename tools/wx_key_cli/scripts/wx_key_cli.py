#!/usr/bin/env python
import argparse
import base64
import ctypes
import json
import re
import sys
import time
from ctypes import wintypes
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DLL = PROJECT_ROOT / "dist" / "wx_key.dll"
DEFAULT_KEY_CACHE = PROJECT_ROOT / "TEST" / "key-cache.json"


def find_weixin_processes():
    try:
        import psutil
    except ImportError as exc:
        raise SystemExit("psutil is required. Install it in the Python environment used to run this script.") from exc

    candidates = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        if proc.info.get("name") != "Weixin.exe":
            continue
        has_weixin_dll = False
        try:
            for mapped in proc.memory_maps(grouped=False):
                if mapped.path and mapped.path.lower().endswith("\\weixin.dll"):
                    has_weixin_dll = True
                    break
        except Exception:
            pass
        candidates.append({"pid": proc.info["pid"], "exe": proc.info.get("exe") or "", "has_weixin_dll": has_weixin_dll})
    return candidates


def select_pid(args):
    if args.pid:
        return args.pid

    processes = find_weixin_processes()
    if not processes:
        raise SystemExit("No Weixin.exe process found. Start and log in to WeChat first.")

    print("Detected Weixin.exe process(es):")
    for item in processes:
        marker = "main-candidate" if item["has_weixin_dll"] else "helper"
        print(f"  pid={item['pid']} {marker} exe={item['exe']}")

    main_candidates = [item for item in processes if item["has_weixin_dll"]]
    if len(main_candidates) == 1:
        return main_candidates[0]["pid"]
    if len(main_candidates) > 1:
        known = ", ".join(str(item["pid"]) for item in main_candidates)
        raise SystemExit(f"Multiple main candidates found: {known}. Re-run with --pid.")

    known = ", ".join(str(item["pid"]) for item in processes)
    raise SystemExit(f"No process with Weixin.dll found. Known Weixin.exe pids: {known}")


def load_wx_key_dll(dll_path: Path):
    if not dll_path.exists():
        raise SystemExit(f"wx_key.dll not found: {dll_path}. Run scripts/build_native.ps1 first.")

    dll = ctypes.CDLL(str(dll_path))
    dll.InitializeHook.argtypes = [wintypes.DWORD]
    dll.InitializeHook.restype = ctypes.c_bool
    dll.PollKeyData.argtypes = [ctypes.c_char_p, ctypes.c_int]
    dll.PollKeyData.restype = ctypes.c_bool
    dll.GetStatusMessage.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    dll.GetStatusMessage.restype = ctypes.c_bool
    dll.CleanupHook.argtypes = []
    dll.CleanupHook.restype = ctypes.c_bool
    dll.GetLastErrorMsg.argtypes = []
    dll.GetLastErrorMsg.restype = ctypes.c_char_p
    return dll


def decode_message(raw: bytes) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8", "gbk", "mbcs"):
        try:
            return raw.decode(encoding).rstrip("\x00")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").rstrip("\x00")


def drain_status(dll):
    status_buffer = ctypes.create_string_buffer(1024)
    level = ctypes.c_int(0)
    while dll.GetStatusMessage(status_buffer, len(status_buffer), ctypes.byref(level)):
        label = {0: "INFO", 1: "OK", 2: "ERROR"}.get(level.value, str(level.value))
        msg = decode_message(status_buffer.value)
        if msg:
            print(f"[{label}] {msg}")
        status_buffer.value = b""


def confirm_or_exit(pid: int, args):
    if args.yes:
        return
    print()
    print("This will install a temporary hook into the running WeChat process.")
    print(f"Target pid: {pid}")
    print("Risk: WeChat may freeze, crash, log out, or be flagged by security software.")
    answer = input("Type YES to continue: ").strip()
    if answer != "YES":
        raise SystemExit("Cancelled.")


def cache_identifiers(wxid: str, account_root: Path | None) -> list[str]:
    identifiers = []
    if wxid:
        identifiers.append(wxid.lower())
    if account_root:
        identifiers.append(account_root.name.lower())
        account_wxid = account_root.name.rsplit("_", 1)[0] if "_" in account_root.name else account_root.name
        if account_wxid:
            identifiers.append(account_wxid.lower())
    return list(dict.fromkeys(identifiers))


def protect_key_for_current_user(key: str) -> str:
    try:
        import win32crypt
    except ImportError as exc:
        raise SystemExit("pywin32/win32crypt is required to save the key cache securely.") from exc
    encrypted = win32crypt.CryptProtectData(key.encode("ascii"), "WeChatMsg safe_decrypt key", None, None, None, 0)
    return base64.b64encode(encrypted).decode("ascii")


def load_key_cache(cache_path: Path) -> dict:
    if not cache_path.exists():
        return {"version": 1, "entries": {}}
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {"version": 1, "entries": {}}
    data.setdefault("version", 1)
    data.setdefault("entries", {})
    return data


def save_cached_key(cache_path: Path, key: str, wxid: str, account_root: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_key_cache(cache_path)
    entries = cache.setdefault("entries", {})
    entry = {
        "key_dpapi": protect_key_for_current_user(key),
        "wxid": wxid,
        "account_root": str(account_root),
    }
    for identifier in cache_identifiers(wxid, account_root):
        entries[identifier] = entry
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def save_key_cache_if_requested(key: str, args):
    if not args.save_cache:
        return

    if not args.src_dir:
        print("[WARN] Key was not cached: pass --src-dir <account-root> to bind the key to an account.")
        return

    account_root = Path(args.src_dir).expanduser().resolve()
    wxid = args.wxid.strip()
    if not wxid:
        wxid = account_root.name.rsplit("_", 1)[0] if "_" in account_root.name else account_root.name

    save_cached_key(Path(args.key_cache).expanduser().resolve(), key, wxid, account_root)
    print(f"Saved key cache: {Path(args.key_cache).expanduser().resolve()}")
    print(f"Cached account: wxid={wxid} account_root={account_root}")


def main():
    parser = argparse.ArgumentParser(description="Capture a WeChat database key through the locally built wx_key.dll.")
    parser.add_argument("--dll", default=str(DEFAULT_DLL), help="Path to wx_key.dll.")
    parser.add_argument("--pid", type=int, help="Weixin.exe pid. Auto-detected when omitted.")
    parser.add_argument("--timeout", type=int, default=60, help="Seconds to wait for a key.")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive confirmation prompt.")
    parser.add_argument("--save-cache", action="store_true", help="Save the captured key to a DPAPI cache.")
    parser.add_argument("--src-dir", default="", help="WeChat v4 account root or db_storage directory.")
    parser.add_argument("--wxid", default="", help="wxid to associate with the cached key.")
    parser.add_argument("--key-cache", default=str(DEFAULT_KEY_CACHE), help="DPAPI key cache path.")
    args = parser.parse_args()

    if sys.platform != "win32":
        raise SystemExit("This tool only works on Windows.")

    pid = select_pid(args)
    confirm_or_exit(pid, args)

    dll_path = Path(args.dll).expanduser().resolve()
    dll = load_wx_key_dll(dll_path)
    print(f"Loading hook DLL: {dll_path}")
    print(f"Initializing hook for pid={pid}...")

    if not dll.InitializeHook(pid):
        err = decode_message(dll.GetLastErrorMsg() or b"")
        raise SystemExit(f"InitializeHook failed: {err}")

    key_re = re.compile(r"^[0-9a-fA-F]{64}$")
    key_buffer = ctypes.create_string_buffer(128)
    deadline = time.monotonic() + args.timeout

    try:
        print("Waiting for key. If nothing happens, unlock/open WeChat and keep it active.")
        while time.monotonic() < deadline:
            drain_status(dll)
            if dll.PollKeyData(key_buffer, len(key_buffer)):
                key = decode_message(key_buffer.value).strip()
                if key_re.fullmatch(key):
                    print()
                    print(f"KEY={key}")
                    save_key_cache_if_requested(key, args)
                    return
                print(f"[WARN] Ignored invalid key payload: {key!r}")
                key_buffer.value = b""
            time.sleep(0.1)
        raise SystemExit(f"Timed out after {args.timeout}s without receiving a key.")
    finally:
        print("Cleaning up hook...")
        dll.CleanupHook()
        drain_status(dll)


if __name__ == "__main__":
    main()
