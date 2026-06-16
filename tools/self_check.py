#!/usr/bin/env python
import importlib
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def check_import(module_name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module_name)
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main():
    checks: list[tuple[str, bool, str]] = []

    for module_name in [
        "psutil",
        "win32crypt",
        "Crypto.Cipher.AES",
        "zstandard",
        "google.protobuf",
        "xmltodict",
        "pysilk",
        "wxManager",
        "exporter",
    ]:
        ok, detail = check_import(module_name)
        checks.append((f"import {module_name}", ok, detail))

    test_root = PROJECT_ROOT / "TEST"
    checks.append(("TEST directory", test_root.exists(), str(test_root)))

    wx_key_dll = PROJECT_ROOT / "tools" / "wx_key_cli" / "dist" / "wx_key.dll"
    wx_key_detail = (
        str(wx_key_dll)
        if wx_key_dll.exists()
        else f"not found at {wx_key_dll}; build with tools\\wx_key_cli\\scripts\\build_native.ps1"
    )
    checks.append(("wx_key.dll", wx_key_dll.exists(), wx_key_detail))

    ffmpeg_path = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")
    checks.append(("ffmpeg", bool(ffmpeg_path), ffmpeg_path or "not found; voice export may be unavailable"))

    failed = 0
    for name, ok, detail in checks:
        status = "OK" if ok else "WARN"
        print(f"[{status}] {name}: {detail}")
        if not ok and name.startswith("import "):
            failed += 1

    if failed:
        raise SystemExit(f"Self check finished with {failed} missing required import(s).")


if __name__ == "__main__":
    main()
