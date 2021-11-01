from libc.stdint cimport int16_t
from libcpp.string cimport string


cdef extern from "sink.h" namespace "pensieve::io":
    cdef cppclass Sink:
        pass

    cdef cppclass FileSink(Sink):
        FileSink(const string& file_name) except +IOError

    cdef cppclass SocketSink(Sink):
        SocketSink(string host, unsigned int port) except +IOError
