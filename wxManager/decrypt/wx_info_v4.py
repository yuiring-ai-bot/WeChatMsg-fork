#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@Time        : 2025/1/10 2:36
@Author      : SiYuan
@Email       : 863909694@qq.com
@File        : wxManager-wx_info_v4.py
@Description : 部分思路参考：https://github.com/0xlane/wechat-dump-rs
"""

import ctypes
import multiprocessing
import os.path

import hmac
import os
import struct
import time
from ctypes import wintypes
from multiprocessing import freeze_support

import pymem
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA512
import yara

from wxManager.decrypt.common import WeChatInfo
from wxManager.decrypt.common import get_version

# 定义必要的常量
PROCESS_ALL_ACCESS = 0x1F0FFF
PAGE_READWRITE = 0x04
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000

# Constants
IV_SIZE = 16
HMAC_SHA256_SIZE = 64
HMAC_SHA512_SIZE = 64
KEY_SIZE = 32
AES_BLOCK_SIZE = 16
ROUND_COUNT = 256000
PAGE_SIZE = 4096
SALT_SIZE = 16

finish_flag = False


def key_diagnose_enabled():
    return os.environ.get("WECHATMSG_KEY_DIAG", "").strip().lower() in {"1", "true", "yes", "on"}


def print_key_diagnose(message):
    if key_diagnose_enabled():
        print(f"[key-diagnose] {message}")


def wide_key_scan_enabled():
    return os.environ.get("WECHATMSG_KEY_WIDE", "").strip().lower() in {"1", "true", "yes", "on"}


def address_in_regions(address, regions, size=KEY_SIZE):
    return any(base_address <= address <= base_address + region_size - size for base_address, region_size in regions)


# 定义 MEMORY_BASIC_INFORMATION 结构
class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_ulong),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.c_ulong),
        ("Protect", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
    ]


# Windows API Constants
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

# Load Windows DLLs
kernel32 = ctypes.windll.kernel32


# 打开目标进程
def open_process(pid):
    return ctypes.windll.kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)


# 读取目标进程内存
def read_process_memory(process_handle, address, size):
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t(0)
    success = ctypes.windll.kernel32.ReadProcessMemory(
        process_handle,
        ctypes.c_void_p(address),
        buffer,
        size,
        ctypes.byref(bytes_read)
    )
    if not success:
        return None
    return buffer.raw


# 获取所有内存区域
def get_memory_regions(process_handle):
    regions = []
    mbi = MEMORY_BASIC_INFORMATION()
    address = 0
    while ctypes.windll.kernel32.VirtualQueryEx(
            process_handle,
            ctypes.c_void_p(address),
            ctypes.byref(mbi),
            ctypes.sizeof(mbi)
    ):
        if mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE:
            regions.append((mbi.BaseAddress, mbi.RegionSize))
        address += mbi.RegionSize
    return regions


rules_v4 = r'''
rule GetDataDir {
    strings:
        $a = /[a-zA-Z]:\\(.{1,100}?\\){0,1}?xwechat_files\\[0-9a-zA-Z_-]{6,24}?\\db_storage\\/
    condition:
        $a
}

rule GetPhoneNumberOffset {
    strings:
        $a = /[\x01-\x20]\x00{7}(\x0f|\x1f)\x00{7}[0-9]{11}\x00{5}\x0b\x00{7}\x0f\x00{7}/
    condition:
        $a
}
rule GetKeyAddrStub
{
    strings:
        $a = /.{6}\x00{2}\x00{8}\x20\x00{7}\x2f\x00{7}/
    condition:
        all of them
}
'''


def read_string(data: bytes, offset, size):
    try:
        return data[offset:offset + size].decode('utf-8')
    except:
        # print(data[offset:offset + size])
        # print(traceback.format_exc())
        return ''


def read_num(data: bytes, offset, size):
    # 构建格式字符串，根据 size 来选择相应的格式
    if size == 1:
        fmt = '<B'  # 1 字节，unsigned char
    elif size == 2:
        fmt = '<H'  # 2 字节，unsigned short
    elif size == 4:
        fmt = '<I'  # 4 字节，unsigned int
    elif size == 8:
        fmt = '<Q'  # 8 字节，unsigned long long
    else:
        raise ValueError("Unsupported size")

    # 使用 struct.unpack 从指定 offset 开始读取 size 字节的数据并转换为数字
    result = struct.unpack_from(fmt, data, offset)[0]  # 通过 unpack_from 来读取指定偏移的数据
    return result


def read_bytes(data: bytes, offset, size):
    return data[offset:offset + size]


# def read_bytes_from_pid(pid, offset, size):
#     with open(f'/proc/{pid}/mem', 'rb') as mem_file:
#         mem_file.seek(offset)
#         return mem_file.read(size)


# 导入 Windows API 函数
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID, ctypes.c_size_t,
                              ctypes.POINTER(ctypes.c_size_t)]
ReadProcessMemory.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL


def read_bytes_from_pid(pid: int, addr: int, size: int):
    # 打开进程
    hprocess = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not hprocess:
        raise Exception(f"Failed to open process with PID {pid}")
    buffer = b''
    try:
        # 创建缓冲区
        buffer = ctypes.create_string_buffer(size)

        # 读取内存
        bytes_read = ctypes.c_size_t(0)
        success = ReadProcessMemory(hprocess, addr, buffer, size, ctypes.byref(bytes_read))
        if not success:
            CloseHandle(hprocess)
            return b''
            raise Exception(f"Failed to read memory at address {hex(addr)}")

        # 关闭句柄
        CloseHandle(hprocess)
    except:
        pass
    # 返回读取的字节数组
    return bytes(buffer)


def read_string_from_pid(pid: int, addr: int, size: int):
    bytes0 = read_bytes_from_pid(pid, addr, size)
    try:
        return bytes0.decode('utf-8')
    except:
        return ''


def is_ok(passphrase, buf):
    global finish_flag
    if finish_flag:
        return False
    if not buf or len(buf) < PAGE_SIZE:
        return False
    # 获取文件开头的 salt
    salt = buf[:SALT_SIZE]
    # salt 异或 0x3a 得到 mac_salt，用于计算 HMAC
    mac_salt = bytes(x ^ 0x3a for x in salt)
    # 使用 PBKDF2 生成新的密钥
    new_key = PBKDF2(passphrase, salt, dkLen=KEY_SIZE, count=ROUND_COUNT, hmac_hash_module=SHA512)
    # 使用新的密钥和 mac_salt 计算 mac_key
    mac_key = PBKDF2(new_key, mac_salt, dkLen=KEY_SIZE, count=2, hmac_hash_module=SHA512)
    # 计算 hash 校验码的保留空间
    reserve = IV_SIZE + HMAC_SHA512_SIZE
    reserve = ((reserve + AES_BLOCK_SIZE - 1) // AES_BLOCK_SIZE) * AES_BLOCK_SIZE
    # 校验 HMAC
    start = SALT_SIZE
    end = PAGE_SIZE
    mac = hmac.new(mac_key, buf[start:end - reserve + IV_SIZE], SHA512)
    mac.update(struct.pack('<I', 1))  # page number as 1
    hash_mac = mac.digest()
    # 校验 HMAC 是否一致
    hash_mac_start_offset = end - reserve + IV_SIZE
    hash_mac_end_offset = hash_mac_start_offset + len(hash_mac)
    if hash_mac == buf[hash_mac_start_offset:hash_mac_end_offset]:
        print_key_diagnose("candidate key passed database HMAC verification")
        finish_flag = True
        return True
    return False


def check_chunk(chunk, bufs):
    global finish_flag
    if finish_flag:
        return False
    for name, buf in bufs:
        if is_ok(chunk, buf):
            print_key_diagnose(f"candidate key verified by {name}")
            return chunk
    return False


def verify_key(key: bytes, buffer: bytes, flag, result):
    if len(key) != 32:
        return False
    if flag.value:  # 如果其他进程已找到结果，提前退出
        return False
    if is_ok(key, buffer):  # 替换为实际的目标检测条件
        print_key_diagnose("key found")
        with flag.get_lock():  # 保证线程安全
            flag.value = True
            return key
    else:
        return False


def get_key_(keys, bufs):
    if not keys:
        print_key_diagnose("no candidate key bytes to verify")
        return None
    if isinstance(bufs, bytes):
        bufs = [("legacy-buffer", bufs)]
    if not bufs:
        print_key_diagnose("no database buffers available for key verification")
        return None
    print_key_diagnose(f"verifying {len(keys)} unique candidate key byte sequence(s)")
    pool = multiprocessing.Pool(processes=multiprocessing.cpu_count() // 2)
    results = pool.starmap(check_chunk, ((key, bufs) for key in keys))
    pool.close()
    pool.join()

    for r in results:
        if r:
            print_key_diagnose("key found")
            return bytes.hex(r)
    print_key_diagnose("all candidate key byte sequences failed database HMAC verification")
    return None


def get_key_inner(pid, process_infos):
    """
    扫描可能为key的内存
    :param pid:
    :param process_infos:
    :return:
    """
    process_handle = open_process(pid)
    rules_v4_key = r'''
        rule GetKeyAddrStub
        {
            strings:
                $a = /.{6}\x00{2}\x00{8}\x20\x00{7}\x2f\x00{7}/
            condition:
                all of them
        }
        '''
    rules = yara.compile(source=rules_v4_key)
    pre_addresses = []
    stats = {
        "regions": len(process_infos),
        "readable_regions": 0,
        "rule_match_regions": 0,
        "candidate_addresses": 0,
        "nearby_pointer_values": 0,
        "invalid_pointer_values": 0,
        "memory_read_failures": 0,
        "empty_key_reads": 0,
    }
    wide_scan = wide_key_scan_enabled()
    for base_address, region_size in process_infos:
        memory = read_process_memory(process_handle, base_address, region_size)
        # 定义目标数据（如内存或文件内容）
        target_data = memory  # 二进制数据
        if not memory:
            stats["memory_read_failures"] += 1
            continue
        stats["readable_regions"] += 1
        # 加上这些判断条件时灵时不灵
        # if b'-----BEGIN PUBLIC KEY-----' not in target_data or b'USER_KEYINFO' not in target_data:
        #     continue
        # if b'db_storage' not in memory:
        #     continue
        # with open(f'key-{base_address}.bin', 'wb') as f:
        #     f.write(target_data)
        matches = rules.match(data=target_data)
        if matches:
            stats["rule_match_regions"] += 1
            for match in matches:
                rule_name = match.rule
                if rule_name == 'GetKeyAddrStub':
                    for string in match.strings:
                        instance = string.instances[0]
                        offset, content = instance.offset, instance.matched_data
                        addr = read_num(target_data, offset, 8)
                        pre_addresses.append(addr)
                        stats["candidate_addresses"] += 1
                        if wide_scan:
                            start_offset = max(0, offset - 64)
                            end_offset = min(len(target_data) - 8, offset + len(content) + 64)
                            for candidate_offset in range(start_offset, end_offset + 1, 8):
                                pointer_value = read_num(target_data, candidate_offset, 8)
                                stats["nearby_pointer_values"] += 1
                                if address_in_regions(pointer_value, process_infos):
                                    pre_addresses.append(pointer_value)
                                    stats["candidate_addresses"] += 1
                                else:
                                    stats["invalid_pointer_values"] += 1
    keys = []
    key_set = set()
    for pre_address in pre_addresses:
        if address_in_regions(pre_address, process_infos):
            key = read_bytes_from_pid(pid, pre_address, 32)
            if not key:
                stats["empty_key_reads"] += 1
                continue
            if key not in key_set:
                keys.append(key)
                key_set.add(key)
    stats["unique_key_reads"] = len(keys)
    return keys, stats


def get_key(pid, process_handle, buf):
    if isinstance(buf, bytes):
        bufs = [("legacy-buffer", buf)]
    else:
        bufs = buf
    print_key_diagnose(f"database verification buffer count: {len(bufs)}")
    process_infos = get_memory_regions(process_handle)
    print_key_diagnose(f"private committed memory region count: {len(process_infos)}")
    if not process_infos:
        print_key_diagnose("no private committed memory regions found")
        return None

    def split_list(lst, n):
        k, m = divmod(len(lst), n)
        return (lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n))

    keys = []
    chunk_count = min(len(process_infos), 40)
    pool = multiprocessing.Pool(processes=multiprocessing.cpu_count() // 2)
    results = pool.starmap(get_key_inner, ((pid, process_info_) for process_info_ in
                                           split_list(process_infos, chunk_count)))
    pool.close()
    pool.join()
    totals = {
        "chunks": chunk_count,
        "regions": 0,
        "readable_regions": 0,
        "rule_match_regions": 0,
        "candidate_addresses": 0,
        "nearby_pointer_values": 0,
        "invalid_pointer_values": 0,
        "memory_read_failures": 0,
        "empty_key_reads": 0,
        "unique_key_reads": 0,
    }
    for r in results:
        if r:
            chunk_keys, chunk_stats = r
            keys += chunk_keys
            for name in totals:
                if name != "chunks":
                    totals[name] += chunk_stats.get(name, 0)
    print_key_diagnose(
        "scan summary: "
        f"chunks={totals['chunks']} regions={totals['regions']} "
        f"readable={totals['readable_regions']} rule_match_regions={totals['rule_match_regions']} "
        f"candidate_addresses={totals['candidate_addresses']} "
        f"nearby_pointer_values={totals['nearby_pointer_values']} "
        f"invalid_pointer_values={totals['invalid_pointer_values']} "
        f"unique_key_reads={totals['unique_key_reads']} "
        f"memory_read_failures={totals['memory_read_failures']} "
        f"empty_key_reads={totals['empty_key_reads']}"
    )
    key = get_key_(keys, bufs)
    return key


def read_validation_buffers(wx_db_storage_dir):
    candidates = [
        ("favorite/favorite_fts.db", os.path.join(wx_db_storage_dir, "favorite", "favorite_fts.db")),
        ("head_image/head_image.db", os.path.join(wx_db_storage_dir, "head_image", "head_image.db")),
        ("contact/contact.db", os.path.join(wx_db_storage_dir, "contact", "contact.db")),
        ("message/message_0.db", os.path.join(wx_db_storage_dir, "message", "message_0.db")),
        ("message/message_1.db", os.path.join(wx_db_storage_dir, "message", "message_1.db")),
    ]
    buffers = []
    for name, db_file_path in candidates:
        if not os.path.exists(db_file_path):
            print_key_diagnose(f"validation db missing: {name}")
            continue
        size = os.path.getsize(db_file_path)
        if size < PAGE_SIZE:
            print_key_diagnose(f"validation db skipped: {name} size={size} < {PAGE_SIZE}")
            continue
        with open(db_file_path, "rb") as f:
            page = f.read(PAGE_SIZE)
        header = page[:16].hex()
        print_key_diagnose(f"validation db loaded: {name} size={size} first16={header}")
        buffers.append((name, page))
    return buffers


def get_wx_dir(process_handle):
    rules_v4_dir = r'''
    rule GetDataDir {
        strings:
            $a = /[a-zA-Z]:\\(.{1,100}?\\){0,1}?xwechat_files\\[0-9a-zA-Z_-]{6,24}?\\db_storage\\/
        condition:
            $a
    }
    '''
    rules = yara.compile(source=rules_v4_dir)
    process_infos = get_memory_regions(process_handle)
    wx_dir_cnt = {}
    for base_address, region_size in process_infos:
        memory = read_process_memory(process_handle, base_address, region_size)
        # 定义目标数据（如内存或文件内容）
        target_data = memory  # 二进制数据
        if not memory:
            continue
        if b'db_storage' not in memory:
            continue
        matches = rules.match(data=target_data)
        if matches:
            # 输出匹配结果
            for match in matches:
                rule_name = match.rule
                if rule_name == 'GetDataDir':
                    for string in match.strings:
                        content = string.instances[0].matched_data
                        wx_dir_cnt[content] = wx_dir_cnt.get(content, 0) + 1
    return max(wx_dir_cnt, key=wx_dir_cnt.get).decode('utf-8') if wx_dir_cnt else ''


def get_nickname(pid):
    process_handle = open_process(pid)
    if not process_handle:
        print(f"无法打开进程 {pid}")
        return {}
    process_infos = get_memory_regions(process_handle)
    # 加载规则
    r'''$a = /(.{16}[\x00-\x20]\x00{7}(\x0f|\x1f)\x00{7}){2}.{16}[\x01-\x20]\x00{7}(\x0f|\x1f)\x00{7}[0-9]{11}\x00{5}\x0b\x00{7}\x0f\x00{7}.{25}\x00{7}(\x3f|\x2f|\x1f|\x0f)\x00{7}/s'''
    rules_v4_phone = r'''
    rule GetPhoneNumberOffset {
        strings:
            $a = /[\x01-\x20]\x00{7}(\x0f|\x1f)\x00{7}[0-9]{11}\x00{5}\x0b\x00{7}\x0f\x00{7}/
        condition:
            $a
    }
    '''
    nick_name = ''
    phone = ''
    account_name = ''
    rules = yara.compile(source=rules_v4_phone)
    for base_address, region_size in process_infos:
        memory = read_process_memory(process_handle, base_address, region_size)
        # 定义目标数据（如内存或文件内容）
        target_data = memory  # 二进制数据
        if not memory:
            continue
        # if not (b'db_storage' in target_data or b'USER_KEYINFO' in target_data):
        #     continue
        # if not (b'-----BEGIN PUBLIC KEY-----' in target_data):
        #     continue
        matches = rules.match(data=target_data)
        if matches:
            # 输出匹配结果
            for match in matches:
                rule_name = match.rule
                if rule_name == 'GetPhoneNumberOffset':
                    for string in match.strings:
                        instance = string.instances[0]
                        offset, content = instance.offset, instance.matched_data
                        phone_addr = offset + 0x10
                        phone = read_string(target_data, phone_addr, 11)

                        # 提取前 8 个字节
                        data_slice = target_data[offset:offset + 8]
                        # 使用 struct.unpack() 将字节转换为 u64，'<Q' 表示小端字节序的 8 字节无符号整数
                        nick_name_length = struct.unpack('<Q', data_slice)[0]
                        # print('nick_name_length', nick_name_length)
                        nick_name = read_string(target_data, phone_addr - 0x20, nick_name_length)
                        a = target_data[phone_addr - 0x60:phone_addr + 0x50]
                        account_name_length = read_num(target_data, phone_addr - 0x30, 8)
                        # print('account_name_length', account_name_length)
                        account_name = read_string(target_data, phone_addr - 0x40, account_name_length)
                        if not account_name:
                            addr = read_num(target_data, phone_addr - 0x40, 8)
                            # print(hex(addr))
                            account_name = read_string_from_pid(pid, addr, account_name_length)
    return {
        'nick_name': nick_name,
        'phone': phone,
        'account_name': account_name
    }


def worker(pid, queue):
    nickname_dic = get_nickname(pid)
    queue.put(nickname_dic)


def dump_wechat_info_v4(pid) -> WeChatInfo | None:
    wechat_info = WeChatInfo()
    wechat_info.pid = pid
    wechat_info.version = get_version(pid)
    process_handle = open_process(pid)
    if not process_handle:
        print(f"无法打开进程 {pid}")
        return wechat_info
    queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=worker, args=(pid, queue))

    process.start()

    wechat_info.wx_dir = get_wx_dir(process_handle)
    # print(wx_dir_cnt)
    if not wechat_info.wx_dir:
        return wechat_info
    bufs = read_validation_buffers(wechat_info.wx_dir)
    if bufs:
        wechat_info.key = get_key(pid, process_handle, bufs)
    else:
        print_key_diagnose("no usable validation database pages found")
    ctypes.windll.kernel32.CloseHandle(process_handle)
    wechat_info.wxid = '_'.join(wechat_info.wx_dir.split('\\')[-3].split('_')[0:-1])
    wechat_info.wx_dir = '\\'.join(wechat_info.wx_dir.split('\\')[:-2])
    process.join()  # 等待子进程完成
    if not queue.empty():
        nickname_info = queue.get()
        wechat_info.nick_name = nickname_info.get('nick_name', '')
        wechat_info.phone = nickname_info.get('phone', '')
        wechat_info.account_name = nickname_info.get('account_name', '')
    if not wechat_info.key:
        wechat_info.errcode = 404
    else:
        wechat_info.errcode = 200
    return wechat_info


if __name__ == '__main__':
    freeze_support()
    st = time.time()
    pm = pymem.Pymem("Weixin.exe")
    pid = pm.process_id
    w = dump_wechat_info_v4(pid)
    print(w)
    et = time.time()
    print(et - st)
