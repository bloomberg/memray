from libcpp.string cimport string
from libcpp.vector cimport vector


cdef extern from "native_resolver.h" namespace "memray::native_resolver":
    vector[string] unwindHere() except+
