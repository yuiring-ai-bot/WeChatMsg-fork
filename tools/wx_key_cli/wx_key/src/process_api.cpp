#include "../include/process_api.h"

bool ProcessApi::initialized = false;
pNtQueryInformationProcess ProcessApi::fnNtQueryInformationProcess = nullptr;

bool ProcessApi::Initialize() {
    if (initialized) {
        return true;
    }

    HMODULE ntdll = GetModuleHandleA("ntdll.dll");
    if (ntdll) {
        fnNtQueryInformationProcess = reinterpret_cast<pNtQueryInformationProcess>(
            GetProcAddress(ntdll, "NtQueryInformationProcess")
        );
    }

    initialized = true;
    return true;
}

void ProcessApi::Cleanup() {
    initialized = false;
    fnNtQueryInformationProcess = nullptr;
}

NTSTATUS ProcessApi::OpenTargetProcess(
    PHANDLE ProcessHandle,
    ACCESS_MASK DesiredAccess,
    PMY_OBJECT_ATTRIBUTES ObjectAttributes,
    PMY_CLIENT_ID ClientId
) {
    (void)ObjectAttributes;
    if (!ProcessHandle || !ClientId || !ClientId->UniqueProcess) {
        return STATUS_UNSUCCESSFUL;
    }

    DWORD pid = static_cast<DWORD>(reinterpret_cast<ULONG_PTR>(ClientId->UniqueProcess));
    HANDLE handle = OpenProcess(DesiredAccess, FALSE, pid);
    if (!handle) {
        *ProcessHandle = nullptr;
        return STATUS_UNSUCCESSFUL;
    }

    *ProcessHandle = handle;
    return STATUS_SUCCESS;
}

NTSTATUS ProcessApi::ReadMemory(
    HANDLE ProcessHandle,
    PVOID BaseAddress,
    PVOID Buffer,
    SIZE_T BufferSize,
    PSIZE_T NumberOfBytesRead
) {
    SIZE_T bytesRead = 0;
    BOOL ok = ReadProcessMemory(ProcessHandle, BaseAddress, Buffer, BufferSize, &bytesRead);
    if (NumberOfBytesRead) {
        *NumberOfBytesRead = bytesRead;
    }
    return ok ? STATUS_SUCCESS : STATUS_UNSUCCESSFUL;
}

NTSTATUS ProcessApi::WriteMemory(
    HANDLE ProcessHandle,
    PVOID BaseAddress,
    PVOID Buffer,
    SIZE_T BufferSize,
    PSIZE_T NumberOfBytesWritten
) {
    SIZE_T bytesWritten = 0;
    BOOL ok = WriteProcessMemory(ProcessHandle, BaseAddress, Buffer, BufferSize, &bytesWritten);
    if (NumberOfBytesWritten) {
        *NumberOfBytesWritten = bytesWritten;
    }
    return ok ? STATUS_SUCCESS : STATUS_UNSUCCESSFUL;
}

NTSTATUS ProcessApi::AllocateMemory(
    HANDLE ProcessHandle,
    PVOID* BaseAddress,
    ULONG_PTR ZeroBits,
    PSIZE_T RegionSize,
    ULONG AllocationType,
    ULONG Protect
) {
    (void)ZeroBits;
    if (!BaseAddress || !RegionSize || *RegionSize == 0) {
        return STATUS_UNSUCCESSFUL;
    }

    PVOID address = VirtualAllocEx(ProcessHandle, *BaseAddress, *RegionSize, AllocationType, Protect);
    if (!address) {
        *BaseAddress = nullptr;
        return STATUS_UNSUCCESSFUL;
    }

    *BaseAddress = address;
    return STATUS_SUCCESS;
}

NTSTATUS ProcessApi::FreeMemory(
    HANDLE ProcessHandle,
    PVOID* BaseAddress,
    PSIZE_T RegionSize,
    ULONG FreeType
) {
    (void)RegionSize;
    if (!BaseAddress || !*BaseAddress) {
        return STATUS_UNSUCCESSFUL;
    }

    BOOL ok = VirtualFreeEx(ProcessHandle, *BaseAddress, 0, FreeType);
    if (ok) {
        *BaseAddress = nullptr;
    }
    return ok ? STATUS_SUCCESS : STATUS_UNSUCCESSFUL;
}

NTSTATUS ProcessApi::ProtectMemory(
    HANDLE ProcessHandle,
    PVOID* BaseAddress,
    PSIZE_T RegionSize,
    ULONG NewProtect,
    PULONG OldProtect
) {
    if (!BaseAddress || !*BaseAddress || !RegionSize || *RegionSize == 0) {
        return STATUS_UNSUCCESSFUL;
    }

    DWORD oldProtect = 0;
    BOOL ok = VirtualProtectEx(ProcessHandle, *BaseAddress, *RegionSize, NewProtect, &oldProtect);
    if (OldProtect) {
        *OldProtect = oldProtect;
    }
    return ok ? STATUS_SUCCESS : STATUS_UNSUCCESSFUL;
}

NTSTATUS ProcessApi::QueryInformationProcess(
    HANDLE ProcessHandle,
    PROCESSINFOCLASS ProcessInformationClass,
    PVOID ProcessInformation,
    ULONG ProcessInformationLength,
    PULONG ReturnLength
) {
    if (!initialized || !fnNtQueryInformationProcess) {
        return STATUS_UNSUCCESSFUL;
    }
    return fnNtQueryInformationProcess(
        ProcessHandle,
        ProcessInformationClass,
        ProcessInformation,
        ProcessInformationLength,
        ReturnLength
    );
}
