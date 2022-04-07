#include <iostream>
#include <stdexcept>
#include <string>

#include "logging.h"

namespace memray {

static int LOG_THRESHOLD = static_cast<int>(logLevel::WARNING);

static const char*
prefixFromLogLevel(int level)
{
    if (level >= CRITICAL) return "Pensieve CRITICAL: ";
    if (level >= ERROR) return "Pensieve ERROR: ";
    if (level >= WARNING) return "Pensieve WARNING: ";
    if (level >= INFO) return "Pensieve INFO: ";
    if (level >= DEBUG) return "Pensieve DEBUG: ";
    return "Pensieve TRACE: ";
}

void
setLogThreshold(int threshold)
{
    LOG_THRESHOLD = threshold;
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
