#pragma once

#include <cstddef>
#include <vector>

#include "records.h"

namespace memray::tracking_api {

inline constexpr size_t NATIVE_TRACE_CACHE_INTERNAL_FRAMES = 1;

__attribute__((noinline)) size_t
captureNativeTrace(std::vector<frame_id_t>& frames);

void
setupNativeTraceCache();

void
flushNativeTraceCache();

}  // namespace memray::tracking_api
