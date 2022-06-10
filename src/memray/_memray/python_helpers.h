#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <functional>
#include <memory>
#include <string>
#include <unordered_map>

namespace memray::python_helpers {
class PyUnicode_Cache
{
  public:
    PyObject* getUnicodeObject(const std::string& str);

  private:
    using py_capsule_t = std::unique_ptr<PyObject, std::function<void(PyObject*)>>;
    std::unordered_map<std::string, py_capsule_t> d_cache{};
};
}  // namespace memray::python_helpers
