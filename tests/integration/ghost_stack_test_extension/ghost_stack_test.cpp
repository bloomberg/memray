#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdexcept>
#include <string>
#include <vector>

#pragma GCC push_options
#pragma GCC optimize("O0")

// ============================================================================
// Exception Test Helpers
// ============================================================================

static int destructor_count = 0;
static std::vector<int> cleanup_order;

struct RAIIGuard
{
    RAIIGuard()
    {
        destructor_count = 0;
    }
    ~RAIIGuard()
    {
        destructor_count++;
    }
};

struct OrderedGuard
{
    int id;
    OrderedGuard(int i)
    : id(i)
    {
        cleanup_order.push_back(id * 10);
    }  // construct
    ~OrderedGuard()
    {
        cleanup_order.push_back(id);
    }  // destruct
};

// Callback to Python function that calls ghost_stack_backtrace
static PyObject* capture_callback = nullptr;

__attribute__((noinline)) static void
call_capture_callback()
{
    if (capture_callback) {
        PyObject* result = PyObject_CallObject(capture_callback, nullptr);
        Py_XDECREF(result);
    }
}

__attribute__((noinline)) static void
throw_with_trace()
{
    call_capture_callback();
    throw std::runtime_error("test exception");
}

__attribute__((noinline)) static void
raii_throw()
{
    RAIIGuard guard;
    call_capture_callback();
    throw std::runtime_error("raii test");
}

__attribute__((noinline)) static void
multi_raii_throw()
{
    OrderedGuard g1(1);
    call_capture_callback();
    OrderedGuard g2(2);
    call_capture_callback();
    OrderedGuard g3(3);
    throw std::runtime_error("multi raii");
}

__attribute__((noinline)) static std::string
nested_try_catch()
{
    try {
        call_capture_callback();
        try {
            call_capture_callback();
            throw std::runtime_error("inner");
        } catch (const std::runtime_error&) {
            call_capture_callback();
            throw std::runtime_error("outer");
        }
    } catch (const std::runtime_error& e) {
        return e.what();
    }
    return "";
}

// ============================================================================
// Python-exposed test functions
// ============================================================================

static PyObject*
set_capture_callback(PyObject* self, PyObject* args)
{
    PyObject* callback;
    if (!PyArg_ParseTuple(args, "O", &callback)) return nullptr;
    Py_XDECREF(capture_callback);
    capture_callback = callback;
    Py_INCREF(capture_callback);
    Py_RETURN_NONE;
}

static PyObject*
test_basic_exception(PyObject* self, PyObject* args)
{
    try {
        throw_with_trace();
        Py_RETURN_FALSE;  // Should not reach here
    } catch (const std::runtime_error& e) {
        if (std::string(e.what()) == "test exception") {
            Py_RETURN_TRUE;
        }
        Py_RETURN_FALSE;
    }
}

static PyObject*
test_raii_cleanup(PyObject* self, PyObject* args)
{
    destructor_count = 0;
    try {
        raii_throw();
    } catch (const std::runtime_error&) {
        // Expected
    }
    return PyLong_FromLong(destructor_count);
}

static PyObject*
test_raii_cleanup_order(PyObject* self, PyObject* args)
{
    cleanup_order.clear();
    try {
        multi_raii_throw();
    } catch (const std::runtime_error&) {
        // Expected
    }
    // Return cleanup_order as a list
    PyObject* result = PyList_New(cleanup_order.size());
    for (size_t i = 0; i < cleanup_order.size(); i++) {
        PyList_SET_ITEM(result, i, PyLong_FromLong(cleanup_order[i]));
    }
    return result;
}

static PyObject*
test_nested_try_catch(PyObject* self, PyObject* args)
{
    std::string result = nested_try_catch();
    return PyUnicode_FromString(result.c_str());
}

static PyObject*
test_different_exception_types(PyObject* self, PyObject* args)
{
    // Test int exception
    try {
        call_capture_callback();
        throw 42;
    } catch (int e) {
        if (e != 42) Py_RETURN_FALSE;
    }

    // Test const char* exception
    try {
        call_capture_callback();
        throw "test string";
    } catch (const char* e) {
        if (std::string(e) != "test string") Py_RETURN_FALSE;
    }

    // Test std::string exception
    try {
        call_capture_callback();
        throw std::string("string exception");
    } catch (const std::string& e) {
        if (e != "string exception") Py_RETURN_FALSE;
    }

    Py_RETURN_TRUE;
}

#pragma GCC pop_options

static PyMethodDef methods[] = {
        {"set_capture_callback",
         set_capture_callback,
         METH_VARARGS,
         "Set callback for ghost_stack capture"},
        {"test_basic_exception",
         test_basic_exception,
         METH_NOARGS,
         "Test basic exception through ghost_stack"},
        {"test_raii_cleanup", test_raii_cleanup, METH_NOARGS, "Test RAII cleanup during unwinding"},
        {"test_raii_cleanup_order",
         test_raii_cleanup_order,
         METH_NOARGS,
         "Test RAII cleanup order (LIFO)"},
        {"test_nested_try_catch", test_nested_try_catch, METH_NOARGS, "Test nested try/catch"},
        {"test_different_exception_types",
         test_different_exception_types,
         METH_NOARGS,
         "Test different exception types"},
        {nullptr, nullptr, 0, nullptr},
};

static struct PyModuleDef moduledef = {PyModuleDef_HEAD_INIT, "ghost_stack_test", "", -1, methods};

PyMODINIT_FUNC
PyInit_ghost_stack_test(void)
{
    return PyModule_Create(&moduledef);
}
