#pragma once

#include <Python.h>

#ifdef __cplusplus
extern "C" {
#endif

int
memray_compat_is_current_or_caller_frame(PyFrameObject* frame);

int
memray_compat_is_parent_frame(PyFrameObject* parent, PyFrameObject* frame);

int
memray_compat_is_monitoring_tool_active(int tool_id, PyObject* tool_name, PyObject* callbacks);

#ifdef __cplusplus
}
#endif
