#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <assert.h>
#include <pthread.h>
#ifdef __linux__
#include <malloc.h>
#endif

#pragma GCC push_options
#pragma GCC optimize ("O0")

// Regular call chain
//
__attribute__((noinline)) static void baz() {
    void* p = valloc(1234);
    free(p);
}

__attribute__((noinline)) static void bar() {
    baz();
}

__attribute__((noinline)) static void foo() {
    bar();
}

PyObject*
run_simple(PyObject* mod , PyObject* arg)
{
    foo();
    Py_RETURN_NONE;
}

__attribute__((noinline)) static void baz_other() {
    void* p = valloc(1234);
    free(p);
}

__attribute__((noinline)) static void bar_other() {
    baz_other();
}

__attribute__((noinline)) static void foo_other() {
    bar_other();
}

PyObject*
run_alternating(PyObject* mod, PyObject* count_object)
{
    long count = PyLong_AsLong(count_object);
    if (count == -1 && PyErr_Occurred()) {
        return NULL;
    }
    for (long i = 0; i < count; ++i) {
        foo();
        foo_other();
    }
    Py_RETURN_NONE;
}

#if defined(__linux__) && defined(__x86_64__)

__attribute__((noinline)) void cfa16_leaf() {
    void* p = valloc(1234);
    free(p);
}

void cfa16_caller_a(void);
void cfa16_caller_b(void);

__asm__(
        ".text\n"
        ".type cfa16_frame, @function\n"
        "cfa16_frame:\n"
        ".cfi_startproc\n"
        "popq %r11\n"
        ".cfi_def_cfa_offset 0\n"
        "leaq .Lcfa16_caller_a_return(%rip), %r10\n"
        "pushq %r10\n"
        ".cfi_def_cfa_offset 8\n"
        "pushq %r11\n"
        ".cfi_def_cfa_offset 16\n"
        ".cfi_offset %rip, -16\n"
        "call cfa16_leaf\n"
        "popq %r11\n"
        ".cfi_def_cfa_offset 8\n"
        "addq $8, %rsp\n"
        ".cfi_def_cfa_offset 0\n"
        "jmpq *%r11\n"
        ".cfi_endproc\n"
        ".size cfa16_frame, .-cfa16_frame\n"
        ".globl cfa16_caller_a\n"
        ".type cfa16_caller_a, @function\n"
        "cfa16_caller_a:\n"
        ".cfi_startproc\n"
        "subq $8, %rsp\n"
        ".cfi_def_cfa_offset 16\n"
        "call cfa16_frame\n"
        ".Lcfa16_caller_a_return:\n"
        "addq $8, %rsp\n"
        ".cfi_def_cfa_offset 8\n"
        "retq\n"
        ".cfi_endproc\n"
        ".size cfa16_caller_a, .-cfa16_caller_a\n"
        ".globl cfa16_caller_b\n"
        ".type cfa16_caller_b, @function\n"
        "cfa16_caller_b:\n"
        ".cfi_startproc\n"
        "subq $8, %rsp\n"
        ".cfi_def_cfa_offset 16\n"
        "call cfa16_frame\n"
        ".Lcfa16_caller_b_return:\n"
        "addq $8, %rsp\n"
        ".cfi_def_cfa_offset 8\n"
        "retq\n"
        ".cfi_endproc\n"
        ".size cfa16_caller_b, .-cfa16_caller_b\n");

__attribute__((noinline)) static void invoke_cfa16_callers() {
    for (long i = 0; i < 10; ++i) {
        void (*caller)(void) = i < 5 ? cfa16_caller_a : cfa16_caller_b;
        caller();
    }
}

PyObject*
run_cfa16(PyObject* mod, PyObject* arg)
{
    invoke_cfa16_callers();
    Py_RETURN_NONE;
}

#endif

// Inlined call chain

__attribute__((always_inline)) static inline void baz_inline() {
    void *p = valloc(1234);
    free(p);
}

__attribute__((always_inline)) static inline void bar_inline() {
    baz_inline();
}

__attribute__((always_inline)) static inline void foo_inline() {
    bar_inline();
}

PyObject*
run_inline(PyObject* mod, PyObject* arg)
{
    foo_inline();
    Py_RETURN_NONE;
}

void* thread_worker(void* arg)
{
    foo();
    return NULL;
}

PyObject*
run_in_thread(PyObject* mod, PyObject* arg)
{
    pthread_t thread;
    pthread_create(&thread, NULL, &thread_worker, NULL);
    pthread_join(thread, NULL);
    Py_RETURN_NONE;
}

void deep_call(long n) {
    if (n == 0) {
        return foo();
    }
    return deep_call(n-1);
}

PyObject*
run_deep(PyObject* mod, PyObject* n_stack)
{
    long n = PyLong_AsLong(n_stack);
    if (n == -1 && PyErr_Occurred()) {
        return NULL;
    }
    deep_call(n);
    Py_RETURN_NONE;
}


PyObject*
run_recursive(PyObject* mod, PyObject* args)
{
    long n;
    PyObject* callback;
    if (!PyArg_ParseTuple(args, "lO", &n, &callback)) {
        return NULL;
    }
    if (n <= 0) {
        foo();
        Py_RETURN_NONE;
    }
    return PyObject_CallFunction(callback, "i", n-1);
}

#pragma GCC pop_options

static PyMethodDef methods[] = {
        {"run_simple", run_simple, METH_NOARGS, "Execute a chain of native functions"},
        {"run_alternating", run_alternating, METH_O, "Alternate between two native call chains"},
#if defined(__linux__) && defined(__x86_64__)
        {"run_cfa16", run_cfa16, METH_NOARGS, "Use a frame whose return address is at CFA - 16"},
#endif
        {"run_inline", run_inline, METH_NOARGS, "Execute a chain of native inlined_functions"},
        {"run_in_thread", run_in_thread, METH_NOARGS, "Like run_simple, but in a bg thread"},
        {"run_deep", run_deep, METH_O, "Execute a chain of native inlined functions in a deep stack"},
        {"run_recursive", run_recursive, METH_VARARGS, "Execute a callback if the second argument is bigger than 0"},
        {NULL, NULL, 0, NULL},
};

static struct PyModuleDef moduledef = {PyModuleDef_HEAD_INIT, "native_ext", "", -1, methods};

PyMODINIT_FUNC
PyInit_native_ext(void)
{
    PyObject *mod = PyModule_Create(&moduledef);
#ifdef Py_GIL_DISABLED
    PyUnstable_Module_SetGIL(mod, Py_MOD_GIL_NOT_USED);
#endif
    return mod;
}
