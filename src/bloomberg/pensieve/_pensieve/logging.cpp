#include <stdexcept>
#include <string>

#include "../_pensieve_api.h"
#include "logging.h"

namespace pensieve {

static int LOGGER_INITIALIZED = false;

void
initializePythonLoggerInterface()
{
    import_bloomberg__pensieve___pensieve();
    LOGGER_INITIALIZED = true;
}

void
logWithPython(const std::string& message, int level)
{
    if (!LOGGER_INITIALIZED) {
        throw std::runtime_error("Logger is not initialized");
    }

    PyGILState_STATE gstate;
    gstate = PyGILState_Ensure();
    if (!PyErr_Occurred() && Py_IsInitialized()) {
        log_with_python(message, level);
    }
    PyGILState_Release(gstate);
}

}  // namespace pensieve
