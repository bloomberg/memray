from libcpp.string cimport string


cdef extern from "sink.h" namespace "pensieve::io":
    cdef cppclass Sink:
        pass

    cdef cppclass FileSink(Sink):
        FileSink(const string& file_name)

    cdef cppclass SocketSink(Sink):
        SocketSink(int port)
