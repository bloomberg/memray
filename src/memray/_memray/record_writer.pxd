from _memray.records cimport FileFormat
from _memray.sink cimport Sink
from libcpp cimport bool
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string


cdef extern from "record_writer.h" namespace "memray::api":
    cdef cppclass RecordWriter:
        pass
    cdef unique_ptr[RecordWriter] createRecordWriter(
        unique_ptr[Sink],
        string command_line,
        bool native_trace,
        FileFormat file_format,
        bool trace_python_allocators,
    ) except+
