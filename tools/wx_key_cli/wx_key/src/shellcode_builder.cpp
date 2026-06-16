#include "../include/shellcode_builder.h"
#include "../include/ipc_manager.h"
#include <xbyak/xbyak.h>
#include <cstddef>

namespace {
    constexpr size_t kSharedDataSizeOffset = offsetof(SharedKeyData, dataSize);
    constexpr size_t kSharedKeyBufferOffset = offsetof(SharedKeyData, keyBuffer);
    constexpr size_t kSharedSequenceOffset = offsetof(SharedKeyData, sequenceNumber);
}

ShellcodeBuilder::ShellcodeBuilder() {
    shellcode.reserve(512);
}

ShellcodeBuilder::~ShellcodeBuilder() {
}

void ShellcodeBuilder::Clear() {
    shellcode.clear();
}

size_t ShellcodeBuilder::GetShellcodeSize() const {
    return shellcode.size();
}

// 使用 Xbyak 生成 Hook Shellcode
std::vector<BYTE> ShellcodeBuilder::BuildHookShellcode(const ShellcodeConfig& config) {
    shellcode.clear();

    // 只支持 x64
    if (sizeof(void*) != 8) {
        return shellcode;
    }

    // 生成机器码
    Xbyak::CodeGenerator code(1024, Xbyak::AutoGrow);

    Xbyak::Label skipCopy;

    auto emitSaveRegs = [&]() {
        code.pushfq();
        code.push(code.rax);
        code.push(code.rcx);
        code.push(code.rdx);
        code.push(code.rbx);
        code.push(code.rbp);
        code.push(code.rsi);
        code.push(code.rdi);
        code.push(code.r8);
        code.push(code.r9);
        code.push(code.r10);
        code.push(code.r11);
        code.push(code.r12);
        code.push(code.r13);
        code.push(code.r14);
        code.push(code.r15);
    };

    auto emitRestoreRegs = [&]() {
        code.pop(code.r15);
        code.pop(code.r14);
        code.pop(code.r13);
        code.pop(code.r12);
        code.pop(code.r11);
        code.pop(code.r10);
        code.pop(code.r9);
        code.pop(code.r8);
        code.pop(code.rdi);
        code.pop(code.rsi);
        code.pop(code.rbp);
        code.pop(code.rbx);
        code.pop(code.rdx);
        code.pop(code.rcx);
        code.pop(code.rax);
        code.popfq();
    };

    // ===== 保存寄存器/标志位 =====
    emitSaveRegs();

    // ===== keySize 检查 =====
    code.mov(code.rax, code.ptr[code.rdx + 0x10]); // rax = keySize
    code.cmp(code.rax, 32);
    code.jne(skipCopy);

    // ===== 拷贝 32 字节密钥到共享内存 =====
    code.mov(code.rcx, code.ptr[code.rdx + 0x08]); // rcx = pKeyBuffer
    code.mov(code.rdx, (uint64_t)config.sharedMemoryAddress);
    code.mov(code.rdi, code.rdx);
    code.mov(code.dword[code.rdi + static_cast<uint32_t>(kSharedDataSizeOffset)], 32);            // dataSize = 32
    code.add(code.rdi, static_cast<uint32_t>(kSharedKeyBufferOffset));     // rdi -> keyBuffer
    code.mov(code.rsi, code.rcx);                  // rsi = source
    code.mov(code.rcx, 32);                        // count
    code.rep();
    code.movsb();                                  // rep movsb

    // ===== 递增序列号 =====
    code.mov(code.eax, code.dword[code.rdx + static_cast<uint32_t>(kSharedSequenceOffset)]); // 读取 sequenceNumber
    code.inc(code.eax);
    code.mov(code.dword[code.rdx + static_cast<uint32_t>(kSharedSequenceOffset)], code.eax); // 写回递增后的序列号

    code.L(skipCopy);

    // ===== 恢复寄存器/标志位 =====
    emitRestoreRegs();

    // ===== 跳回 Trampoline =====
    code.mov(code.rax, (uint64_t)config.trampolineAddress);
    code.jmp(code.rax);

    // 输出机器码
    shellcode.assign(code.getCode(), code.getCode() + code.getSize());
    return shellcode;
}
