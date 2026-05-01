#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <assert.h>
#include <pthread.h>
#include <stdlib.h>

#ifdef __linux__
#include <features.h>
#include <malloc.h>
#endif

// Weak forward declarations so the test extension builds against pre-C23
// libc headers but can still call free_sized / free_aligned_sized when the
// running process is linked against a newer libc.
#if defined(__linux__) && (!defined(__GLIBC__) || !__GLIBC_PREREQ(2, 42))
extern "C" {
void free_sized(void* ptr, size_t size) __attribute__((weak));
void free_aligned_sized(void* ptr, size_t alignment, size_t size) __attribute__((weak));
}
#endif

namespace {  // unnamed

#pragma GCC push_options
#pragma GCC optimize ("O0")

const int NUM_THREADS = 100;
const int NUM_BUFFERS = 100;
pthread_t threads[NUM_THREADS];

extern "C" void
allocate_memory()
{
    unsigned long* buffers[NUM_BUFFERS];
    for (int i=0; i < NUM_BUFFERS; ++i) {
        int ret = posix_memalign((void**)buffers+i, sizeof(void*), sizeof(void*)*(i+1));
        if (ret) {
            buffers[i] = NULL;
            break;
        }
    }
    for (int i=0; i < NUM_BUFFERS; ++i) {
        free(buffers[i]);
    }
}

extern "C" void*
worker(void*)
{
    allocate_memory();
    return NULL;
}

void start_threads()
{
    for (int i=0; i<NUM_THREADS; ++i) {
        pthread_t thread;
        int ret = pthread_create(&thread, NULL, &worker, NULL);
        assert(0 == ret);
        threads[i] = thread;
    }
}

void join_threads()
{
    for (int i=0; i<NUM_THREADS; ++i) {
        pthread_join(threads[i], NULL);
    }
}

__attribute__((optnone)) static void cleanup_handler(void* arg) {
  void* data = valloc(sizeof(int));
  free(data);
}

static void* create_tls_in_thread(void *arg) {
  pthread_key_t thread_specific_storage;
  pthread_key_create(&thread_specific_storage, cleanup_handler);
  pthread_setspecific(thread_specific_storage, (void*)12);
  pthread_exit(NULL);
  return NULL;
}

void valloc_on_thread_exit() {
  pthread_t thread_id;
  void *result;
  pthread_create(&thread_id, NULL, create_tls_in_thread, NULL);
  pthread_join(thread_id, &result);
}

PyObject*
run(PyObject*, PyObject*)
{
    start_threads();
    join_threads();
    Py_RETURN_NONE;
}

PyObject*
run_valloc_at_exit(PyObject*, PyObject*)
{
    valloc_on_thread_exit();
    Py_RETURN_NONE;
}

PyObject*
has_free_sized(PyObject*, PyObject*)
{
#if defined(__linux__)
    if (&free_sized != nullptr && &free_aligned_sized != nullptr) {
        Py_RETURN_TRUE;
    }
#endif
    Py_RETURN_FALSE;
}

PyObject*
run_free_sized(PyObject*, PyObject*)
{
#if defined(__linux__)
    if (&free_sized == nullptr || &free_aligned_sized == nullptr) {
        PyErr_SetString(PyExc_RuntimeError, "libc lacks free_sized / free_aligned_sized");
        return NULL;
    }
    const size_t plain_size = 128;
    void* p = malloc(plain_size);
    if (!p) return PyErr_NoMemory();
    free_sized(p, plain_size);

    const size_t alignment = 64;
    const size_t aligned_size = 256;
    void* q = aligned_alloc(alignment, aligned_size);
    if (!q) return PyErr_NoMemory();
    free_aligned_sized(q, alignment, aligned_size);

    return Py_BuildValue("(KK)", (unsigned long long)p, (unsigned long long)q);
#else
    PyErr_SetString(PyExc_RuntimeError, "free_sized only tested on Linux");
    return NULL;
#endif
}

#pragma GCC pop_options

}  // unnamed namespace

static PyMethodDef methods[] = {
        {"run", run, METH_NOARGS, "Run a bunch of threads"},
        {"run_valloc_at_exit", run_valloc_at_exit, METH_NOARGS, "Run valloc while exiting a thread"},
        {"has_free_sized", has_free_sized, METH_NOARGS, "Whether libc provides C23 sized deallocators"},
        {"run_free_sized", run_free_sized, METH_NOARGS, "Allocate and free using C23 sized deallocators"},
        {NULL, NULL, 0, NULL},
};

static struct PyModuleDef moduledef = {PyModuleDef_HEAD_INIT, "testext", "", -1, methods};

PyMODINIT_FUNC
PyInit_testext(void)
{
    PyObject *mod = PyModule_Create(&moduledef);
#ifdef Py_GIL_DISABLED
    PyUnstable_Module_SetGIL(mod, Py_MOD_GIL_NOT_USED);
#endif
    return mod;
}
