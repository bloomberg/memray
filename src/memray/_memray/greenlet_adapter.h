#pragma once
#include <cstdint>
namespace memray::tracking_api::greenlet_adapter {
void
beginTracking();
void
endTracking();
void
markModuleLoaded();
uintptr_t
currentIdentity();
// Fresh result from currentIdentity, valid until the corresponding capture.
bool
threadKnownAbsent();
void
forgetAllocation(void* pointer);
void
childFork();
}  // namespace memray::tracking_api::greenlet_adapter
