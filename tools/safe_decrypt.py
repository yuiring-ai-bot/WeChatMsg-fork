#!/usr/bin/env python
import argparse
import base64
import ctypes
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from ctypes import wintypes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = (PROJECT_ROOT / "TEST").resolve()
sys.path.insert(0, str(PROJECT_ROOT))


class MODULEINFO(ctypes.Structure):
    _fields_ = [
        ("lpBaseOfDll", ctypes.c_void_p),
        ("SizeOfImage", wintypes.DWORD),
        ("EntryPoint", ctypes.c_void_p),
    ]


def match_pattern(data: bytes, offset: int, pattern: bytes, mask: str) -> bool:
    for index, expected in enumerate(pattern):
        if mask[index] != "?" and data[offset + index] != expected:
            return False
    return True


def find_pattern_matches(process_handle, base_address: int, image_size: int, pattern: bytes, mask: str):
    kernel32 = ctypes.windll.kernel32
    chunk_size = 4 * 1024 * 1024
    overlap = len(pattern)
    matches = []
    offset = 0

    while offset < image_size:
        read_size = min(chunk_size + overlap, image_size - offset)
        buffer = ctypes.create_string_buffer(read_size)
        bytes_read = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(
            process_handle,
            ctypes.c_void_p(base_address + offset),
            buffer,
            read_size,
            ctypes.byref(bytes_read),
        )
        if ok and bytes_read.value >= len(pattern):
            data = buffer.raw[:bytes_read.value]
            for index in range(0, bytes_read.value - len(pattern) + 1):
                if match_pattern(data, index, pattern, mask):
                    matches.append(base_address + offset + index)
        offset += chunk_size

    return matches


def scan_wx_key_hook_pattern(process_handle):
    psapi = ctypes.WinDLL("Psapi.dll")
    psapi.EnumProcessModulesEx.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HMODULE),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
    ]
    psapi.EnumProcessModulesEx.restype = wintypes.BOOL
    psapi.GetModuleBaseNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.HMODULE,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    psapi.GetModuleBaseNameW.restype = wintypes.DWORD
    psapi.GetModuleInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.HMODULE,
        ctypes.POINTER(MODULEINFO),
        wintypes.DWORD,
    ]
    psapi.GetModuleInformation.restype = wintypes.BOOL

    hmodule_array = (wintypes.HMODULE * 2048)()
    needed = wintypes.DWORD(0)
    list_modules_all = 0x03

    if not psapi.EnumProcessModulesEx(
        process_handle,
        hmodule_array,
        ctypes.sizeof(hmodule_array),
        ctypes.byref(needed),
        list_modules_all,
    ):
        print("[diagnose]   wx_key_pattern_scan=failed enum_modules")
        return

    count = min(needed.value // ctypes.sizeof(wintypes.HMODULE), len(hmodule_array))
    weixin_module = None
    for index in range(count):
        name_buffer = ctypes.create_unicode_buffer(260)
        if psapi.GetModuleBaseNameW(process_handle, hmodule_array[index], name_buffer, len(name_buffer)):
            if name_buffer.value.lower() == "weixin.dll":
                weixin_module = hmodule_array[index]
                break

    if not weixin_module:
        print("[diagnose]   wx_key_pattern_scan=skipped no_Weixin.dll_module")
        return

    module_info = MODULEINFO()
    if not psapi.GetModuleInformation(
        process_handle,
        weixin_module,
        ctypes.byref(module_info),
        ctypes.sizeof(module_info),
    ):
        print("[diagnose]   wx_key_pattern_scan=failed module_info")
        return

    pattern = bytes([
        0x24, 0x50, 0x48, 0xC7, 0x45, 0x00, 0xFE, 0xFF,
        0xFF, 0xFF, 0x44, 0x89, 0xCF, 0x44, 0x89, 0xC3,
        0x49, 0x89, 0xD6, 0x48, 0x89, 0xCE, 0x48, 0x89,
    ])
    mask = "x" * len(pattern)
    matches = find_pattern_matches(
        process_handle,
        module_info.lpBaseOfDll,
        module_info.SizeOfImage,
        pattern,
        mask,
    )

    base = int(module_info.lpBaseOfDll)
    print(
        "[diagnose]   "
        f"wx_key_pattern_scan=>4.1.6.14 matches={len(matches)} "
        f"weixin_base=0x{base:x} image_size={module_info.SizeOfImage}"
    )
    for match in matches[:5]:
        target = match - 3
        print(
            "[diagnose]   "
            f"wx_key_pattern_match rva=0x{match - base:x} "
            f"target_function_rva=0x{target - base:x}"
        )


def require_inside_test(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(TEST_ROOT)
    except ValueError:
        raise SystemExit(f"{label} must be inside {TEST_ROOT}")
    return resolved


def resolve_v4_account_root(raw_path: str, allow_real_source: bool = False) -> Path:
    src = Path(raw_path).expanduser().resolve()
    if not allow_real_source:
        src = require_inside_test(src, "Source directory")
    if not src.exists() or not src.is_dir():
        raise SystemExit(f"Source directory does not exist: {src}")

    if (src / "db_storage" / "contact" / "contact.db").exists():
        return src
    if (src / "contact" / "contact.db").exists() and src.name.lower() == "db_storage":
        return src.parent

    candidates = list(src.rglob("db_storage/contact/contact.db"))
    if len(candidates) == 1:
        return candidates[0].parents[2]
    if len(candidates) > 1:
        raise SystemExit("Multiple copied v4 account directories found. Pass the exact account root.")
    raise SystemExit("Could not find db_storage/contact/contact.db under the source directory.")


def select_wechat_info(account_root: Path, infos):
    ok_infos = [info for info in infos if getattr(info, "key", "")]
    if not ok_infos:
        raise SystemExit("No usable key found. Make sure WeChat is running and logged in.")

    account_dir_name = account_root.name.lower()
    matches = [
        info for info in ok_infos
        if account_dir_name == info.wxid.lower() or account_dir_name.startswith(info.wxid.lower() + "_")
    ]
    if len(matches) == 1:
        return matches[0]
    if len(ok_infos) == 1:
        return ok_infos[0]

    known = ", ".join(info.wxid for info in ok_infos)
    raise SystemExit(f"Could not match copied account directory to a running WeChat account. Found: {known}")


def print_diagnostics():
    import psutil
    from wxManager.decrypt.common import get_version

    print("[diagnose] Scanning Weixin.exe processes...")
    processes = [
        proc for proc in psutil.process_iter(["pid", "name", "exe"])
        if proc.info.get("name") == "Weixin.exe"
    ]
    if not processes:
        print("[diagnose] No Weixin.exe process found.")
        return

    process_vm_read = 0x0010
    process_query_information = 0x0400
    desired_access = process_vm_read | process_query_information
    for proc in processes:
        pid = proc.info["pid"]
        exe = proc.info.get("exe") or ""
        print(f"[diagnose] pid={pid} exe={exe}")
        try:
            print(f"[diagnose]   version={get_version(pid)}")
        except Exception as exc:
            print(f"[diagnose]   version_error={type(exc).__name__}: {exc}")

        try:
            modules = list(proc.memory_maps(grouped=False))
            weixin_modules = [m.path for m in modules if m.path and "Weixin.dll" in m.path]
            print(f"[diagnose]   module_count={len(modules)} weixin_dll_found={bool(weixin_modules)}")
            for module in weixin_modules[:3]:
                print(f"[diagnose]   weixin_dll={module}")
        except Exception as exc:
            print(f"[diagnose]   memory_maps_error={type(exc).__name__}: {exc}")

        ctypes.set_last_error(0)
        handle = ctypes.windll.kernel32.OpenProcess(desired_access, False, pid)
        err = ctypes.get_last_error()
        if handle:
            print(f"[diagnose]   OpenProcess(PROCESS_VM_READ|PROCESS_QUERY_INFORMATION)=ok")
            if weixin_modules:
                scan_wx_key_hook_pattern(handle)
            ctypes.windll.kernel32.CloseHandle(handle)
        else:
            print(f"[diagnose]   OpenProcess(PROCESS_VM_READ|PROCESS_QUERY_INFORMATION)=failed last_error={err}")


def summarize_infos(infos):
    print(f"[diagnose] get_info_v4 returned {len(infos)} account candidate(s).")
    for info in infos:
        key = getattr(info, "key", "") or ""
        key_summary = "missing"
        if key:
            key_summary = f"present len={len(key)} prefix={key[:6]} suffix={key[-6:]}"
        print(
            "[diagnose] "
            f"pid={info.pid} version={info.version} errcode={info.errcode} "
            f"wxid={info.wxid!r} wx_dir={info.wx_dir!r} key={key_summary}"
        )


def verify_sqlite(db_path: Path) -> None:
    if not db_path.exists():
        raise SystemExit(f"Expected decrypted database was not created: {db_path}")
    con = sqlite3.connect(db_path)
    try:
        con.execute("select name from sqlite_master limit 1").fetchall()
    finally:
        con.close()


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


def protect_key_for_current_user(key: str) -> str:
    try:
        import win32crypt
    except ImportError as exc:
        raise SystemExit("pywin32/win32crypt is required to save the key cache securely.") from exc
    encrypted = win32crypt.CryptProtectData(key.encode("ascii"), "WeChatMsg safe_decrypt key", None, None, None, 0)
    return base64.b64encode(encrypted).decode("ascii")


def unprotect_key_for_current_user(encoded: str) -> str:
    try:
        import win32crypt
    except ImportError as exc:
        raise SystemExit("pywin32/win32crypt is required to read the key cache securely.") from exc
    encrypted = base64.b64decode(encoded.encode("ascii"))
    _, decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
    return decrypted.decode("ascii")


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


def lookup_cached_key(cache_path: Path, wxid: str = "", account_root: Path | None = None):
    cache = load_key_cache(cache_path)
    entries = cache.get("entries", {})
    for identifier in cache_identifiers(wxid, account_root):
        entry = entries.get(identifier)
        if not entry:
            continue
        key = unprotect_key_for_current_user(entry["key_dpapi"])
        if len(key) == 64:
            cached_root = entry.get("account_root", "")
            return key, cached_root, identifier
    return "", "", ""


def lookup_single_cached_account(cache_path: Path):
    cache = load_key_cache(cache_path)
    entries = cache.get("entries", {})
    usable = []
    seen_roots = set()
    for identifier, entry in entries.items():
        account_root = entry.get("account_root", "")
        if not account_root or account_root in seen_roots:
            continue
        key = unprotect_key_for_current_user(entry["key_dpapi"])
        if len(key) == 64 and Path(account_root).exists():
            usable.append((key, account_root, identifier))
            seen_roots.add(account_root)
    if len(usable) == 1:
        return usable[0]
    return "", "", ""


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


def show_key_cache(cache_path: Path) -> None:
    cache = load_key_cache(cache_path)
    entries = cache.get("entries", {})
    if not entries:
        print(f"No cached keys found in {cache_path}")
        return
    print(f"Cached key entries in {cache_path}:")
    shown_roots = set()
    for identifier, entry in sorted(entries.items()):
        account_root = entry.get("account_root", "")
        root_marker = account_root or identifier
        if root_marker in shown_roots:
            continue
        shown_roots.add(root_marker)
        wxid = entry.get("wxid", "")
        exists = Path(account_root).exists() if account_root else False
        print(f"- wxid={wxid or identifier} account_root={account_root or '<missing>'} exists={exists}")


def confirm_unsafe_hook_key_extract(wxid: str, account_root: Path) -> None:
    phrase = f"I AUTHORIZE HOOK KEY EXTRACTION FOR {wxid}"
    print("")
    print("Unsafe hook key extraction was requested.")
    print("This may modify the running WeChat process temporarily.")
    print(f"Account: {wxid}")
    print(f"Source:  {account_root}")
    print(f"Type exactly this phrase to continue: {phrase}")
    typed = input("> ").strip()
    if typed != phrase:
        raise SystemExit("Unsafe hook key extraction was not authorized.")


def run_unsafe_hook_key_extract(wxid: str, account_root: Path) -> str:
    confirm_unsafe_hook_key_extract(wxid, account_root)
    cli_path = PROJECT_ROOT / "tools" / "wx_key_cli" / "scripts" / "wx_key_cli.py"
    dll_path = PROJECT_ROOT / "tools" / "wx_key_cli" / "dist" / "wx_key.dll"
    if not cli_path.exists():
        raise SystemExit(f"Hook backend CLI not found: {cli_path}")
    if not dll_path.exists():
        raise SystemExit(
            f"Hook backend DLL not found: {dll_path}\n"
            "Build it first with:\n"
            "  powershell -ExecutionPolicy Bypass -File tools\\wx_key_cli\\scripts\\build_native.ps1"
        )

    cmd = [
        sys.executable,
        str(cli_path),
        "--dll",
        str(dll_path),
        "--timeout",
        "90",
        "--yes",
        "--src-dir",
        str(account_root),
        "--wxid",
        wxid,
    ]
    print("Starting hook key extraction backend...")
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.returncode != 0:
        raise SystemExit(f"Hook key extraction failed with exit code {proc.returncode}.")

    for line in proc.stdout.splitlines():
        if line.startswith("KEY="):
            key = line.split("=", 1)[1].strip()
            if len(key) == 64:
                return key
    raise SystemExit("Hook key extraction finished but no KEY=... line was returned.")


def main():
    parser = argparse.ArgumentParser(
        description="Safely decrypt a copied WeChat v4 database directory under TEST."
    )
    parser.add_argument("--src-dir", default="", help="Copied account root, real account root, or real db_storage.")
    parser.add_argument(
        "--output-dir",
        default="TEST/decrypted-db",
        help="Output directory under TEST.",
    )
    parser.add_argument("--key", default="", help="Optional 64-char hex database key.")
    parser.add_argument(
        "--cache-key-only",
        action="store_true",
        help="Save --key to the local DPAPI key cache for --src-dir, then exit without decrypting.",
    )
    parser.add_argument(
        "--key-cache",
        default="TEST/key-cache.json",
        help="DPAPI-protected local key cache file under TEST.",
    )
    parser.add_argument("--show-key-cache", action="store_true", help="List cached accounts without showing keys.")
    parser.add_argument("--no-key-cache", action="store_true", help="Do not read or write the local key cache.")
    parser.add_argument(
        "--allow-real-source",
        action="store_true",
        help="Allow reading a source directory outside TEST. Output is still restricted to TEST.",
    )
    parser.add_argument("--diagnose", action="store_true", help="Print WeChat process/key discovery diagnostics.")
    parser.add_argument(
        "--wide-key-scan",
        action="store_true",
        help="Try additional read-only key pointer offsets near each v4 memory rule match.",
    )
    parser.add_argument(
        "--unsafe-hook-key-extract",
        action="store_true",
        help="Require typed confirmation before using a future hook-based key extraction backend.",
    )
    args = parser.parse_args()

    output_root = require_inside_test(Path(args.output_dir), "Output directory")
    key_cache_path = require_inside_test(Path(args.key_cache), "Key cache") if not args.no_key_cache else None

    if args.show_key_cache:
        if not key_cache_path:
            raise SystemExit("--show-key-cache requires the key cache to be enabled.")
        show_key_cache(key_cache_path)
        return

    from wxManager.decrypt import decrypt_v4
    from wxManager.decrypt import get_info_v4
    from wxManager.decrypt.decrypt_dat import get_decode_code_v4

    key = args.key.strip()
    account_root = None
    nickname = ""
    wxid = ""
    key_source = "argument" if key else ""

    if args.wide_key_scan:
        os.environ["WECHATMSG_KEY_WIDE"] = "1"

    if args.diagnose:
        os.environ["WECHATMSG_KEY_DIAG"] = "1"
        print_diagnostics()

    if args.src_dir:
        account_root = resolve_v4_account_root(args.src_dir, args.allow_real_source)
        nickname = account_root.name
        wxid = account_root.name.rsplit("_", 1)[0] if "_" in account_root.name else account_root.name
        if not key and key_cache_path:
            key, cached_root, identifier = lookup_cached_key(key_cache_path, wxid, account_root)
            if key:
                key_source = f"cache:{identifier}"
                print(f"Using cached key for {identifier}.")
    elif not key and key_cache_path:
        key, cached_root, identifier = lookup_single_cached_account(key_cache_path)
        if key:
            account_root = Path(cached_root).resolve()
            nickname = account_root.name
            wxid = account_root.name.rsplit("_", 1)[0] if "_" in account_root.name else account_root.name
            key_source = f"cache:{identifier}"
            print(f"Using cached key for {identifier}.")

    infos = get_info_v4() if (not key or not account_root or args.diagnose) else []
    if args.diagnose:
        summarize_infos(infos)

    if account_root:
        pass
    elif infos:
        info = select_wechat_info(Path(infos[0].wx_dir), infos)
        account_root = Path(info.wx_dir).resolve()
        nickname = info.nick_name or account_root.name
        wxid = info.wxid or account_root.name
    else:
        raise SystemExit("No source directory was provided and no running WeChat v4 account was found.")

    if not key:
        try:
            info = select_wechat_info(account_root, infos)
            key = info.key
            wxid = info.wxid or wxid
            nickname = info.nick_name or nickname
            key_source = "process-read"
        except SystemExit:
            if not args.unsafe_hook_key_extract:
                raise
            key = run_unsafe_hook_key_extract(wxid, account_root)
            key_source = "unsafe-hook"

    if len(key) != 64:
        raise SystemExit("Database key must be a 64-character hex string.")

    if args.cache_key_only:
        if not key_cache_path:
            raise SystemExit("--cache-key-only requires the key cache to be enabled.")
        if key_source.startswith("cache:"):
            print(f"Key cache already contains an entry for {wxid or account_root.name}.")
        else:
            save_cached_key(key_cache_path, key, wxid, account_root)
            print(f"Saved key cache: {key_cache_path}")
        return

    if key_cache_path and key_source != "" and not key_source.startswith("cache:"):
        save_cached_key(key_cache_path, key, wxid, account_root)
        print(f"Saved key cache: {key_cache_path}")

    output_account_root = output_root / account_root.name
    output_db_storage = output_account_root / "db_storage"
    output_db_storage.mkdir(parents=True, exist_ok=True)

    xor_key = get_decode_code_v4(str(account_root))
    decrypt_v4.decrypt_db_files(key, src_dir=str(account_root), dest_dir=str(output_account_root))

    info_data = {
        "username": wxid,
        "nickname": nickname,
        "wx_dir": str(account_root),
        "xor_key": xor_key,
    }
    with open(output_db_storage / "info.json", "w", encoding="utf-8") as f:
        json.dump(info_data, f, ensure_ascii=False, indent=4)

    verify_sqlite(output_db_storage / "contact" / "contact.db")
    print(f"Decryption completed: {output_db_storage}")


if __name__ == "__main__":
    main()
