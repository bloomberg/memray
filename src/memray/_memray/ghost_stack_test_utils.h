#pragma once

#include <Python.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// Returns a Python list of frame addresses from ghost_stack_backtrace
// Returns Py_None if MEMRAY_HAS_GHOST_STACK is not defined
PyObject* ghost_stack_test_backtrace(void);

// Returns a Python list of frame addresses from unw_backtrace (libunwind)
// Returns Py_None if MEMRAY_HAS_GHOST_STACK is not defined
PyObject* libunwind_test_backtrace(void);

// Reset ghost_stack shadow stack
void ghost_stack_test_reset(void);

// Initialize ghost_stack
void ghost_stack_test_init(void);

// Check if ghost_stack support is available
int ghost_stack_test_has_support(void);

#ifdef __cplusplus
}
#endif
