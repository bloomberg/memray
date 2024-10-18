from _memray.records cimport AllocationRecord
from _memray.records cimport CodeObjectInfo
from _memray.records cimport FileFormat
from _memray.records cimport FramePop
from _memray.records cimport FramePush
from _memray.records cimport HeaderRecord
from _memray.records cimport ImageSegments
from _memray.records cimport MemoryRecord
from _memray.records cimport ObjectRecord
from _memray.records cimport ThreadRecord
from _memray.records cimport UnresolvedNativeFrame
from _memray.records cimport code_object_id_t
from _memray.records cimport thread_id_t
from _memray.sink cimport Sink
from libcpp cimport bool
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string
from libcpp.utility cimport pair
from libcpp.vector cimport vector


cdef extern from *:
    ctypedef struct PyCodeObject:
        pass

    ctypedef struct PyFrameObject:
        pass


cdef extern from "compat.h" namespace "memray::compat":
    char* codeGetLinetable(PyCodeObject*, size_t*)
    int frameGetLasti(PyFrameObject*)


cdef extern from "record_writer.h" namespace "memray::tracking_api":
    cdef cppclass RecordWriter:
        bool writeRecord(const MemoryRecord& record) except+
        bool writeRecord(const pair[code_object_id_t, CodeObjectInfo]& record) except+
        bool writeRecord(const UnresolvedNativeFrame& record) except+
        bool writeMappings(const vector[ImageSegments]& mappings) except+
        bool writeThreadSpecificRecord(thread_id_t tid, const FramePop& record) except+
        bool writeThreadSpecificRecord(thread_id_t tid, const FramePush& record) except+
        bool writeThreadSpecificRecord(thread_id_t tid, const AllocationRecord& record) except+
        bool writeThreadSpecificRecord(thread_id_t tid, const ThreadRecord& record) except+
        bool writeThreadSpecificRecord(thread_id_t tid, const ObjectRecord& record) except+
        bool writeHeader(bool seek_to_start) except+
        bool writeTrailer() except+
        void setMainTidAndSkippedFrames(thread_id_t main_tid, size_t skipped_frames_on_main_tid) except+
        unique_ptr[RecordWriter] cloneInChildProcess() except+

    cdef unique_ptr[RecordWriter] createRecordWriter(
        unique_ptr[Sink],
        string command_line,
        bool native_trace,
        FileFormat file_format,
        bool trace_python_allocators,
        bool track_object_lifetimes,
    ) except+
