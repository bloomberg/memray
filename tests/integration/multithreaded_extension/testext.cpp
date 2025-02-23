#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <assert.h>
#include <pthread.h>

#ifdef __linux__
#include <malloc.h>
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

#pragma GCC pop_options

}  // unnamed namespace

static PyMethodDef methods[] = {
        {"run", run, METH_NOARGS, "Run a bunch of threads"},
        {"run_valloc_at_exit", run_valloc_at_exit, METH_NOARGS, "Run valloc while exiting a thread"},
        {NULL, NULL, 0, NULL},
};

#if PY_MAJOR_VERSION >= 3
static struct PyModuleDef moduledef = {PyModuleDef_HEAD_INIT, "testext", "", -1, methods};

PyMODINIT_FUNC
PyInit_testext(void)
{
    return PyModule_Create(&moduledef);
}
#else
PyMODINIT_FUNC
inittestext(void)
{
    Py_InitModule("testext", methods);
}
#endif
