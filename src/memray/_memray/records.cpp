#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "python_helpers.h"
#include "records.h"

namespace memray::tracking_api {

const char MAGIC[7] = "memray";

PyObject*
Allocation::toPythonObject() const
{
    // We are not using PyBuildValue here because unrolling the
    // operations speeds up the parsing moderately. Additionally, some of
    // the types we need to convert from are not supported by PyBuildValue
    // natively.
    PyObject* tuple = PyTuple_New(8);
    if (tuple == nullptr) {
        return nullptr;
    }

#define __CHECK_ERROR(elem)                                                                             \
    do {                                                                                                \
        if (elem == nullptr) {                                                                          \
            Py_DECREF(tuple);                                                                           \
            return nullptr;                                                                             \
        }                                                                                               \
    } while (0)
    PyObject* elem = PyLong_FromLong(tid);
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 0, elem);
    elem = PyLong_FromUnsignedLong(address);
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 1, elem);
    elem = PyLong_FromSize_t(size);
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 2, elem);
    elem = PyLong_FromLong(static_cast<int>(allocator));
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 3, elem);
    elem = PyLong_FromSize_t(frame_index);
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 4, elem);
    elem = PyLong_FromSize_t(n_allocations);
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 5, elem);
    elem = PyLong_FromSize_t(native_frame_id);
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 6, elem);
    elem = PyLong_FromSize_t(native_segment_generation);
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 7, elem);
#undef __CHECK_ERROR
    return tuple;
}

Allocation
AggregatedAllocation::contributionToHighWaterMark() const
{
    return {
            tid,
            0,
            bytes_in_high_water_mark,
            allocator,
            native_frame_id,
            frame_index,
            native_segment_generation,
            n_allocations_in_high_water_mark,
    };
}

Allocation
AggregatedAllocation::contributionToLeaks() const
{
    return {
            tid,
            0,
            bytes_leaked,
            allocator,
            native_frame_id,
            frame_index,
            native_segment_generation,
            n_allocations_leaked,
    };
}

PyObject*
Frame::toPythonObject(python_helpers::PyUnicode_Cache& pystring_cache) const
{
    PyObject* pyfunction_name = pystring_cache.getUnicodeObject(function_name);
    if (pyfunction_name == nullptr) {
        return nullptr;
    }
    PyObject* pyfilename = pystring_cache.getUnicodeObject(filename);
    if (pyfilename == nullptr) {
        return nullptr;
    }
    PyObject* pylineno = PyLong_FromLong(this->lineno);
    if (pylineno == nullptr) {
        return nullptr;
    }
    PyObject* tuple = PyTuple_New(3);
    if (tuple == nullptr) {
        Py_DECREF(pylineno);
        return nullptr;
    }
    Py_INCREF(pyfunction_name);
    Py_INCREF(pyfilename);
    PyTuple_SET_ITEM(tuple, 0, pyfunction_name);
    PyTuple_SET_ITEM(tuple, 1, pyfilename);
    PyTuple_SET_ITEM(tuple, 2, pylineno);
    return tuple;
}
}  // namespace memray::tracking_api
