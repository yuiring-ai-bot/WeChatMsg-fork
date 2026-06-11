#!/usr/bin/env python
import argparse
import ctypes
import json
import os
import sqlite3
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
    args = parser.parse_args()

    output_root = require_inside_test(Path(args.output_dir), "Output directory")

    from wxManager.decrypt import decrypt_v4
    from wxManager.decrypt import get_info_v4
    from wxManager.decrypt.decrypt_dat import get_decode_code_v4

    key = args.key.strip()
    account_root = None
    nickname = ""
    wxid = ""

    if args.wide_key_scan:
        os.environ["WECHATMSG_KEY_WIDE"] = "1"

    if args.diagnose:
        os.environ["WECHATMSG_KEY_DIAG"] = "1"
        print_diagnostics()

    infos = get_info_v4() if not key or not args.src_dir or args.diagnose else []
    if args.diagnose:
        summarize_infos(infos)

    if args.src_dir:
        account_root = resolve_v4_account_root(args.src_dir, args.allow_real_source)
        nickname = account_root.name
        wxid = account_root.name.rsplit("_", 1)[0] if "_" in account_root.name else account_root.name
    elif infos:
        info = select_wechat_info(Path(infos[0].wx_dir), infos)
        account_root = Path(info.wx_dir).resolve()
        nickname = info.nick_name or account_root.name
        wxid = info.wxid or account_root.name
    else:
        raise SystemExit("No source directory was provided and no running WeChat v4 account was found.")

    if not key:
        info = select_wechat_info(account_root, infos)
        key = info.key
        wxid = info.wxid or wxid
        nickname = info.nick_name or nickname

    if len(key) != 64:
        raise SystemExit("Database key must be a 64-character hex string.")

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
