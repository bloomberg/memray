#include <iostream>
#include <stdexcept>

#include "logging.h"

namespace memray {

static int LOG_THRESHOLD = static_cast<int>(logLevel::WARNING);

static const char*
prefixFromLogLevel(int level)
{
    if (level >= CRITICAL) return "Memray CRITICAL: ";
    if (level >= ERROR) return "Memray ERROR: ";
    if (level >= WARNING) return "Memray WARNING: ";
    if (level >= INFO) return "Memray INFO: ";
    if (level >= DEBUG) return "Memray DEBUG: ";
    return "Memray TRACE: ";
}

void
setLogThreshold(int threshold)
{
    LOG_THRESHOLD = threshold;
}

logLevel
getLogThreshold()
{
    return static_cast<logLevel>(LOG_THRESHOLD);
}

void
logToStderr(const std::string& message, int level)
{
    if (level < LOG_THRESHOLD) {
        return;
    }

    std::cerr << prefixFromLogLevel(level) << message << std::endl;
}

}  // namespace memray
