#define PY_SSIZE_T_CLEAN
#include <patchlevel.h>

#if PY_VERSION_HEX >= 0x030C0000
#    define Py_BUILD_CORE_MODULE
#endif
#include <Python.h>

#if PY_VERSION_HEX >= 0x030C0000
#    include "internal/pycore_frame.h"
#    if PY_VERSION_HEX >= 0x030E0000
#        include "internal/pycore_interp_structs.h"
#        include "internal/pycore_interpframe.h"
#    else
#        include "internal/pycore_interp.h"
#    endif
#    undef Py_BUILD_CORE
#    undef Py_BUILD_CORE_MODULE
#endif

#include "compat_internal.h"

int
memray_compat_is_current_or_caller_frame(PyFrameObject* frame)
{
#if PY_VERSION_HEX >= 0x030C0000
    PyThreadState* tstate = PyGILState_GetThisThreadState();
    if (!tstate) {
        return 0;
    }

#    if PY_VERSION_HEX < 0x030D0000
    _PyInterpreterFrame* current = tstate->cframe ? tstate->cframe->current_frame : NULL;
#    else
    _PyInterpreterFrame* current = tstate->current_frame;
#    endif
    current = _PyFrame_GetFirstComplete(current);
    if (!current) {
        return 0;
    }
    if (current->frame_obj == frame) {
        return 1;
    }
    _PyInterpreterFrame* caller = _PyFrame_GetFirstComplete(current->previous);
    return caller && caller->frame_obj == frame;
#else
    (void)frame;
#endif
    return 0;
}

int
memray_compat_is_parent_frame(PyFrameObject* parent, PyFrameObject* frame)
{
#if PY_VERSION_HEX >= 0x030C0000
    _PyInterpreterFrame* previous = frame->f_frame->previous;
    previous = _PyFrame_GetFirstComplete(previous);
    return previous && previous->frame_obj == parent;
#else
    (void)parent;
    (void)frame;
#endif
    return 0;
}

int
memray_compat_is_monitoring_tool_active(int tool_id, PyObject* tool_name, PyObject* callbacks)
{
#if PY_VERSION_HEX >= 0x030C0000
    static const int events[] = {
            PY_MONITORING_EVENT_PY_START,
            PY_MONITORING_EVENT_PY_RESUME,
            PY_MONITORING_EVENT_PY_RETURN,
            PY_MONITORING_EVENT_PY_YIELD,
            PY_MONITORING_EVENT_PY_UNWIND,
            PY_MONITORING_EVENT_PY_THROW,
    };
    const Py_ssize_t event_count = sizeof(events) / sizeof(events[0]);
    PyThreadState* tstate = PyGILState_GetThisThreadState();
    if (!tstate || !tool_name || !callbacks || !PyTuple_CheckExact(callbacks)
        || PyTuple_GET_SIZE(callbacks) != event_count || tool_id < 0
        || tool_id >= PY_MONITORING_TOOL_IDS)
    {
        return 0;
    }

    PyInterpreterState* interp = PyThreadState_GetInterpreter(tstate);
    if (interp->monitoring_tool_names[tool_id] != tool_name) {
        return 0;
    }

    const uint8_t tool = 1U << tool_id;
    const _Py_GlobalMonitors* monitors = &interp->monitors;
    for (Py_ssize_t i = 0; i < event_count; ++i) {
        if (interp->monitoring_callables[tool_id][events[i]] != PyTuple_GET_ITEM(callbacks, i)
            || !(monitors->tools[events[i]] & tool))
        {
            return 0;
        }
    }
    return 1;
#else
    (void)tool_id;
    (void)tool_name;
    (void)callbacks;
    return 0;
#endif
}
