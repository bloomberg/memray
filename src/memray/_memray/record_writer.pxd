from _memray.sink cimport Sink
from libcpp cimport bool
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string


cdef extern from "record_writer.h" namespace "memray::api":
    cdef cppclass RecordWriter:
        RecordWriter(unique_ptr[Sink], string command_line, bool native_trace) except+
