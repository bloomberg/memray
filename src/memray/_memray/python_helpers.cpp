#include "python_helpers.h"

namespace memray::python_helpers {
PyObject*
PyUnicode_Cache::getUnicodeObject(const std::string& str)
{
    auto it = d_cache.find(str);
    if (it == d_cache.end()) {
        PyObject* pystring = PyUnicode_FromString(str.c_str());
        if (pystring == nullptr) {
            return nullptr;
        }
        auto pystring_capsule = py_capsule_t(pystring, [](auto obj) { Py_DECREF(obj); });
        it = d_cache.emplace(str, std::move(pystring_capsule)).first;
    }
    return it->second.get();
}
}  // namespace memray::python_helpers
