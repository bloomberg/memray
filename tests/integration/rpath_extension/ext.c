#include <Python.h>
#include <dlfcn.h>


static PyObject *hello_world(PyObject *self, PyObject *args) {
    // Load the shared library
    void *lib_handle = dlopen("sharedlib.so", RTLD_LAZY);

    if (!lib_handle) {
        PyErr_SetString(PyExc_RuntimeError, dlerror());
        return NULL;
    }

    // Get the function pointer
    void (*my_shared_function)() = dlsym(lib_handle, "my_shared_function");
    if (!my_shared_function) {
        PyErr_SetString(PyExc_RuntimeError, dlerror());
        dlclose(lib_handle);
        return NULL;
    }

    // Call the function
    my_shared_function();

    // Close the shared library
    dlclose(lib_handle);

    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    {"hello_world", hello_world, METH_NOARGS, "Print Hello, World!"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "ext",
    NULL,
    -1,
    methods
};

PyMODINIT_FUNC PyInit_ext(void) {
    return PyModule_Create(&module);
}
