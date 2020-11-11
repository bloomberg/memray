#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <assert.h>
#include <pthread.h>

const int NUM_THREADS = 100;
const int NUM_BUFFERS = 100;
pthread_t threads[NUM_THREADS];

void*
worker(void*)
{
    unsigned long* buffers[NUM_BUFFERS];
    for (int i=0; i < NUM_BUFFERS; ++i) {
        buffers[i] = (unsigned long*) valloc(i);
    }
    for (int i=0; i < NUM_BUFFERS; ++i) {
        free(buffers[i]);
    }
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

PyObject*
run(PyObject*, PyObject*)
{
    start_threads();
    join_threads();
    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
        {"run", run, METH_NOARGS, "Run a bunch of threads"},
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

