#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "frameobject.h"
#include <cassert>
#include <string>

namespace memray::compat {

inline int
isPythonFinalizing()
{
#if PY_VERSION_HEX >= 0x030D0000
    return Py_IsFinalizing();
#else
    return _Py_IsFinalizing();
#endif
}

inline bool
isEntryFrame(PyFrameObject* frame)
{
#if PY_VERSION_HEX >= 0x030B0000
    return _PyFrame_IsEntryFrame(frame);
#else
    (void)frame;
    return true;
#endif
}

inline PyFrameObject*
threadStateGetFrame(PyThreadState* tstate)
{
#if PY_VERSION_HEX < 0x030B0000
    // Prior to Python 3.11 this was exposed.
    return tstate->frame;
#else
    // Return a borrowed reference.
    PyFrameObject* ret = PyThreadState_GetFrame(tstate);
    if (ret) {
        assert(Py_REFCNT(ret) >= 2);
        Py_DECREF(ret);
    }
    return ret;
#endif
}

inline PyCodeObject*
frameGetCode(PyFrameObject* frame)
{
#if PY_VERSION_HEX < 0x030B0000
    // Prior to Python 3.11 this was exposed.
    return frame->f_code;
#else
    // Return a borrowed reference.
    PyCodeObject* ret = PyFrame_GetCode(frame);
    assert(Py_REFCNT(ret) >= 2);
    Py_DECREF(ret);
    return ret;
#endif
}

inline PyFrameObject*
frameGetBack(PyFrameObject* frame)
{
#if PY_VERSION_HEX < 0x030B0000
    // Prior to Python 3.11 this was exposed.
    return frame->f_back;
#else
    // Return a borrowed reference.
    PyFrameObject* ret = PyFrame_GetBack(frame);
    if (ret) {
        assert(Py_REFCNT(ret) >= 2);
        Py_DECREF(ret);
    }
    return ret;
#endif
}

inline int
frameGetLasti(PyFrameObject* frame)
{
#if PY_VERSION_HEX < 0x030B0000
    // Prior to Python 3.11 this was exposed.
    return frame->f_lasti;
#else
    // Use PyFrame_GetLasti for Python 3.11+
    return PyFrame_GetLasti(frame);
#endif
}

inline PyInterpreterState*
threadStateGetInterpreter(PyThreadState* tstate)
{
#if PY_VERSION_HEX < 0x03090000
    return tstate->interp;
#else
    return PyThreadState_GetInterpreter(tstate);
#endif
}

#if PY_VERSION_HEX >= 0x030E0000

extern "C" void
_PyEval_StopTheWorld(PyInterpreterState*);
extern "C" void
_PyEval_StartTheWorld(PyInterpreterState*);

inline void
stopTheWorld(PyInterpreterState* interp)
{
    _PyEval_StopTheWorld(interp);
}

inline void
startTheWorld(PyInterpreterState* interp)
{
    _PyEval_StartTheWorld(interp);
}

#else

inline void
stopTheWorld(PyInterpreterState*)
{
}

inline void
startTheWorld(PyInterpreterState*)
{
}

#endif

void
setprofileAllThreads(Py_tracefunc func, PyObject* arg);

inline const char*
codeGetLinetable(PyCodeObject* code, size_t* size)
{
#if PY_VERSION_HEX >= 0x030A0000
    // Python 3.10+ uses co_linetable
    PyObject* linetable = code->co_linetable;
#else
    // Python 3.9 and earlier use co_lnotab
    PyObject* linetable = code->co_lnotab;
#endif

    if (linetable && PyBytes_Check(linetable)) {
        *size = PyBytes_GET_SIZE(linetable);
        return PyBytes_AS_STRING(linetable);
    }
    *size = 0;
    return nullptr;
}

// Location information structure for line table parsing
struct LocationInfo
{
    int lineno;
    int end_lineno;
    int column;
    int end_column;
};

bool
parseLinetable(
        int python_version,
        const std::string& linetable,
        uintptr_t addrq,
        int firstlineno,
        LocationInfo* info);

#if PY_VERSION_HEX >= 0x030D0000
using RefTracer = PyRefTracer;
using RefTracerEvent = PyRefTracerEvent;
#else
typedef enum { RefTracer_CREATE = 0, RefTracer_DESTROY = 1 } RefTracerEvent;
using RefTracer = int (*)(PyObject*, RefTracerEvent event, void* data);
#endif

inline int
refTracerSetTracer(RefTracer tracer, void* data)
{
#if PY_VERSION_HEX >= 0x030D0000
    return PyRefTracer_SetTracer(tracer, data);
#else
    return 0;
#endif
}

}  // namespace memray::compat
