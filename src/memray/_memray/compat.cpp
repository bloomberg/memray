#include "compat.h"

namespace memray::compat {

void
setprofileAllThreads(Py_tracefunc func, PyObject* arg)
{
    assert(PyGILState_Check());
#if PY_VERSION_HEX >= 0x030D0000
    PyEval_SetProfileAllThreads(func, arg);
#else
    PyThreadState* this_tstate = PyThreadState_Get();
    PyInterpreterState* interp = threadStateGetInterpreter(this_tstate);
    for (PyThreadState* tstate = PyInterpreterState_ThreadHead(interp); tstate != nullptr;
         tstate = PyThreadState_Next(tstate))
    {
#    if PY_VERSION_HEX >= 0x03090000
        if (_PyEval_SetProfile(tstate, func, arg) < 0) {
            _PyErr_WriteUnraisableMsg("in PyEval_SetProfileAllThreads", nullptr);
        }
#    else
        // For 3.7 and 3.8, backport _PyEval_SetProfile from 3.9
        // https://github.com/python/cpython/blob/v3.9.13/Python/ceval.c#L4738-L4767
        PyObject* profileobj = tstate->c_profileobj;

        tstate->c_profilefunc = NULL;
        tstate->c_profileobj = NULL;
        /* Must make sure that tracing is not ignored if 'profileobj' is freed */
        tstate->use_tracing = tstate->c_tracefunc != NULL;
        Py_XDECREF(profileobj);

        Py_XINCREF(arg);
        tstate->c_profileobj = arg;
        tstate->c_profilefunc = func;

        /* Flag that tracing or profiling is turned on */
        tstate->use_tracing = (func != NULL) || (tstate->c_tracefunc != NULL);
#    endif
    }
#endif
}

}  // namespace memray::compat
