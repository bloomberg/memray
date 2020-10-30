#include <iostream>
#include <malloc.h>
#include <mutex>

#include <Python.h>

#include "elf_shenanigans.h"
#include "guards.h"
#include "hooks.h"
#include "logging.h"

namespace {
static void
prepare_fork()
{
    // Don't do any custom track_allocation handling while inside fork
    RecursionGuard::isActive = true;
}

static void
parent_fork()
{
    // We can continue tracking
    RecursionGuard::isActive = false;
}

static void
child_fork()
{
    // TODO: allow children to be tracked
    RecursionGuard::isActive = true;
}
}  // namespace

namespace pensieve::tracking_api {
static FILE* out = nullptr;

void
track_allocation(void* ptr, size_t size, const char* func)
{
    if (RecursionGuard::isActive || !out) {
        return;
    }
    RecursionGuard guard;
    // TODO: Do proper tracking here that works without the GIL
    PyGILState_STATE gstate;
    gstate = PyGILState_Ensure();
    LOG(INFO) << func << "(" << size << ") = " << ptr;
    PyGILState_Release(gstate);
}

void
track_deallocation(void* ptr, const char* func)
{
    if (RecursionGuard::isActive || !out) {
        return;
    }
    RecursionGuard recursion_guard;
    // TODO: Do proper tracking here that works without the GIL
    PyGILState_STATE gstate;
    gstate = PyGILState_Ensure();
    LOG(INFO) << func << "(" << ptr << ")";
    PyGILState_Release(gstate);
}

void
invalidate_module_cache()
{
    elf::overwrite_symbols();
}
}  // namespace pensieve::tracking_api

namespace pensieve::api {

void
attach_init()
{
    static std::once_flag once;
    call_once(once, [] { pthread_atfork(&prepare_fork, &parent_fork, &child_fork); });
    tracking_api::out = stderr;

    RecursionGuard guard;
    elf::overwrite_symbols();
}

void
attach_fini()
{
    if (!tracking_api::out) {
        return;
    }
    RecursionGuard guard;
    elf::restore_symbols();
    tracking_api::out = NULL;
}
}  // namespace pensieve::api
