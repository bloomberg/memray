from libc.stdint cimport int16_t
from libcpp cimport bool
from libcpp.string cimport string


cdef extern from "sink.h" namespace "memray::io":
    cdef cppclass Sink:
        pass

    cdef cppclass FileSink(Sink):
        FileSink(const string& file_name, bool overwrite, bool compress) except +IOError

    cdef cppclass SocketSink(Sink):
        SocketSink(string host, unsigned int port) except +IOError

    cdef cppclass NullSink(Sink):
        NullSink() except +IOError
