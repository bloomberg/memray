#pragma once

struct RecursionGuard
{
    RecursionGuard()
    : wasLocked(isActive)
    {
        isActive = true;
    }

    ~RecursionGuard()
    {
        isActive = wasLocked;
    }

    const bool wasLocked;
    __attribute__((tls_model("local-dynamic"))) static thread_local bool isActive;
};
