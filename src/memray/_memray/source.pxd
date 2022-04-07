from libcpp cimport bool
from libcpp.string cimport string


cdef extern from "source.h" namespace "memray::io":
    cdef cppclass Source:
        pass

    cdef cppclass FileSource(Source):
        FileSource(const string& file_name) except+ IOError

    cdef cppclass SocketSource(Source):
        SocketSource(int port) except+ IOError
