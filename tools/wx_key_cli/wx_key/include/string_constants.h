#ifndef STRING_CONSTANTS_H
#define STRING_CONSTANTS_H

#include <string>

namespace ToolStrings {
    inline std::string GetSharedMemoryName() {
        return "Global\\WxKeySharedMemory_{GUID}";
    }

    inline std::string GetEventName() {
        return "Global\\WxKeyEvent_{GUID}";
    }

    inline std::string GetWeixinDllName() {
        return "Weixin.dll";
    }
}

#endif // STRING_CONSTANTS_H
