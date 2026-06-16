# wx_key_cli

Minimal command-line wrapper for the `wx_key.dll` native key capture code.

This repository intentionally removes the original Flutter graphical interface and keeps only:

- the native C++ controller source
- official MinHook source used at build time
- xbyak headers used at build time
- a PowerShell build script
- a Python CLI for one-time key capture and DPAPI cache writing

## Build

Requires Windows, Visual Studio 2022 or Build Tools 2022 with:

- Desktop development with C++
- MSVC v143
- Windows 10/11 SDK

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_native.ps1
```

The DLL is generated at:

```text
dist\wx_key.dll
```

## Capture Key

Run WeChat first, then:

```powershell
python scripts\wx_key_cli.py --timeout 90
```

To write a cache compatible with WeChatMsg `tools/safe_decrypt.py`:

```powershell
python scripts\wx_key_cli.py --timeout 90 --save-cache --src-dir "C:\Users\you\Documents\xwechat_files\wxid_xxx_xxxx" --key-cache "C:\path\to\WeChatMsg\TEST\key-cache.json"
```

The script requires interactive confirmation unless `--yes` is passed.

## Safety Notes

This tool temporarily hooks a running WeChat process. It can make WeChat freeze, crash, log out, or trigger security software. Use it once, save the key cache, then stop using the hook path for normal decrypt/export work.

No prebuilt project DLL or MinHook library is checked in. Build artifacts are ignored.
