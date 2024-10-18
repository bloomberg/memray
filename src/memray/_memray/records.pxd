from _memray.hooks cimport Allocator
from libc.stdint cimport uint64_t
from libc.stdint cimport uintptr_t
from libcpp cimport bool
from libcpp.string cimport string
from libcpp.vector cimport vector


cdef extern from "hooks.h" namespace "memray::hooks":
    cdef enum Allocator:
        MALLOC "memray::hooks::Allocator::MALLOC"
        CALLOC "memray::hooks::Allocator::CALLOC"
        REALLOC "memray::hooks::Allocator::REALLOC"
        VALLOC "memray::hooks::Allocator::VALLOC"
        ALIGNED_ALLOC "memray::hooks::Allocator::ALIGNED_ALLOC"
        POSIX_MEMALIGN "memray::hooks::Allocator::POSIX_MEMALIGN"
        MEMALIGN "memray::hooks::Allocator::MEMALIGN"
        PVALLOC "memray::hooks::Allocator::PVALLOC"
        FREE "memray::hooks::Allocator::FREE"
        PYMALLOC_MALLOC "memray::hooks::Allocator::PYMALLOC_MALLOC"
        PYMALLOC_CALLOC "memray::hooks::Allocator::PYMALLOC_CALLOC"
        PYMALLOC_REALLOC "memray::hooks::Allocator::PYMALLOC_REALLOC"
        PYMALLOC_FREE "memray::hooks::Allocator::PYMALLOC_FREE"

cdef extern from "records.h" namespace "memray::tracking_api":
   ctypedef unsigned long thread_id_t
   ctypedef size_t frame_id_t
   ctypedef size_t code_object_id_t
   ctypedef long long millis_t

   struct CodeObjectInfo:
       string function_name
       string filename
       string linetable
       int firstlineno

   struct AllocationRecord:
       uintptr_t address
       size_t size
       Allocator allocator
       frame_id_t native_frame_id

   struct Frame:
       code_object_id_t code_object_id
       int instruction_offset
       bool is_entry_frame

   struct FramePush:
       Frame frame

   struct FramePop:
       size_t count

   struct ThreadRecord:
       const char* name

   struct Segment:
       uintptr_t vaddr
       size_t memsz

   struct ImageSegments:
       string filename
       uintptr_t addr
       vector[Segment] segments

   struct UnresolvedNativeFrame:
       uintptr_t ip
       frame_id_t index

   struct TrackerStats:
       size_t n_allocations
       size_t n_frames
       long long start_time
       long long end_time

   cdef enum FileFormat:
       ALL_ALLOCATIONS 'memray::tracking_api::FileFormat::ALL_ALLOCATIONS'
       AGGREGATED_ALLOCATIONS 'memray::tracking_api::FileFormat::AGGREGATED_ALLOCATIONS'

   struct HeaderRecord:
       int version
       bool native_traces
       FileFormat file_format
       TrackerStats stats
       string command_line
       int pid
       size_t main_tid
       size_t skipped_frames_on_main_tid
       int python_allocator
       bool trace_python_allocators
       bool track_object_lifetimes

   cdef cppclass Allocation:
       thread_id_t tid
       uintptr_t address
       size_t size
       Allocator allocator
       frame_id_t native_frame_id
       size_t frame_index
       size_t native_segment_generation
       size_t n_allocations

       object toPythonObject()

   cdef cppclass AggregatedAllocation:
       thread_id_t tid
       Allocator allocator
       frame_id_t native_frame_id
       size_t frame_index
       size_t native_segment_generation

       size_t n_allocations_in_high_water_mark
       size_t n_allocations_leaked
       size_t bytes_in_high_water_mark
       size_t bytes_leaked

       Allocation contributionToHighWaterMark()
       Allocation contributionToLeaks()

   struct MemoryRecord:
       uint64_t ms_since_epoch
       size_t rss

   struct MemorySnapshot:
       uint64_t ms_since_epoch
       size_t rss
       size_t heap

   cdef cppclass TrackedObject:
       thread_id_t tid
       uintptr_t address
       bool is_created
       frame_id_t native_frame_id
       size_t frame_index
       size_t native_segment_generation

       object toPythonObject()

   cdef cppclass ObjectRecord:
       uintptr_t address
       bool is_created
       frame_id_t native_frame_id

cdef extern from "<optional>":
   # Cython doesn't have libcpp.optional yet, so just declare this opaquely.
   cdef cppclass optional_location_id_t "std::optional<memray::api::location_id_t>":
       pass
