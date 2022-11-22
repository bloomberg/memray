#include "Python.h"
#if PY_VERSION_HEX >= 0x030B0000
#    define Py_BUILD_CORE 1
#    include "cpython/code.h"
#    undef Py_BUILD_CORE
#endif

#include "cpython_shenanigans.h"

namespace memray::compat {
bool
isLineArrayInitialized(PyCodeObject* obj)
{
#if PY_VERSION_HEX >= 0x030B0000
    return obj->_co_linearray != NULL;
#else
    return true;
#endif
}
}  // namespace memray::compat
