from _pensieve.sink cimport Sink
from libcpp cimport bool
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string


cdef extern from "record_writer.h" namespace "pensieve::api":
    cdef cppclass RecordWriter:
        RecordWriter(unique_ptr[Sink], string command_line, bool native_trace) except+
