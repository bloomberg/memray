from _pensieve.sink cimport Sink
from libcpp.memory cimport unique_ptr


cdef extern from "record_writer.h" namespace "pensieve::api":
    cdef cppclass RecordWriter:
        RecordWriter(unique_ptr[Sink]) except+
