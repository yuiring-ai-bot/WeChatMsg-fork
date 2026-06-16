#ifndef PROCESS_API_H
#define PROCESS_API_H

#include <Windows.h>
#include <winternl.h>

#ifndef STATUS_SUCCESS
#define STATUS_SUCCESS ((NTSTATUS)0x00000000L)
#endif

#ifndef STATUS_UNSUCCESSFUL
#define STATUS_UNSUCCESSFUL ((NTSTATUS)0xC0000001L)
#endif

#ifndef _CLIENT_ID_DEFINED
#define _CLIENT_ID_DEFINED
typedef struct _MY_CLIENT_ID {
    PVOID UniqueProcess;
    PVOID UniqueThread;
} MY_CLIENT_ID, *PMY_CLIENT_ID;
#endif

#ifndef _MY_OBJECT_ATTRIBUTES_DEFINED
#define _MY_OBJECT_ATTRIBUTES_DEFINED
typedef struct _MY_OBJECT_ATTRIBUTES {
    ULONG Length;
    HANDLE RootDirectory;
    PVOID ObjectName;
    ULONG Attributes;
    PVOID SecurityDescriptor;
    PVOID SecurityQualityOfService;
} MY_OBJECT_ATTRIBUTES, *PMY_OBJECT_ATTRIBUTES;
#endif

typedef NTSTATUS(NTAPI* pNtQueryInformationProcess)(
    HANDLE ProcessHandle,
    PROCESSINFOCLASS ProcessInformationClass,
    PVOID ProcessInformation,
    ULONG ProcessInformationLength,
    PULONG ReturnLength
);

class ProcessApi {
public:
    static bool Initialize();
    static void Cleanup();

    static NTSTATUS OpenTargetProcess(
        PHANDLE ProcessHandle,
        ACCESS_MASK DesiredAccess,
        PMY_OBJECT_ATTRIBUTES ObjectAttributes,
        PMY_CLIENT_ID ClientId
    );

    static NTSTATUS ReadMemory(
        HANDLE ProcessHandle,
        PVOID BaseAddress,
        PVOID Buffer,
        SIZE_T BufferSize,
        PSIZE_T NumberOfBytesRead
    );

    static NTSTATUS WriteMemory(
        HANDLE ProcessHandle,
        PVOID BaseAddress,
        PVOID Buffer,
        SIZE_T BufferSize,
        PSIZE_T NumberOfBytesWritten
    );

    static NTSTATUS AllocateMemory(
        HANDLE ProcessHandle,
        PVOID* BaseAddress,
        ULONG_PTR ZeroBits,
        PSIZE_T RegionSize,
        ULONG AllocationType,
        ULONG Protect
    );

    static NTSTATUS FreeMemory(
        HANDLE ProcessHandle,
        PVOID* BaseAddress,
        PSIZE_T RegionSize,
        ULONG FreeType
    );

    static NTSTATUS ProtectMemory(
        HANDLE ProcessHandle,
        PVOID* BaseAddress,
        PSIZE_T RegionSize,
        ULONG NewProtect,
        PULONG OldProtect
    );

    static NTSTATUS QueryInformationProcess(
        HANDLE ProcessHandle,
        PROCESSINFOCLASS ProcessInformationClass,
        PVOID ProcessInformation,
        ULONG ProcessInformationLength,
        PULONG ReturnLength
    );

private:
    static bool initialized;
    static pNtQueryInformationProcess fnNtQueryInformationProcess;
};

#endif // PROCESS_API_H
