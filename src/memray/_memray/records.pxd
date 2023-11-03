from _memray.hooks cimport Allocator
from libc.stdint cimport uintptr_t
from libcpp cimport bool
from libcpp.string cimport string
from libcpp.vector cimport vector


cdef extern from "records.h" namespace "memray::tracking_api":
   ctypedef unsigned long thread_id_t
   ctypedef size_t frame_id_t

   struct Frame:
       string function_name
       string filename
       int lineno

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
       unsigned long int ms_since_epoch
       size_t rss

   struct MemorySnapshot:
       unsigned long int ms_since_epoch
       size_t rss
       size_t heap


cdef extern from "<optional>":
   # Cython doesn't have libcpp.optional yet, so just declare this opaquely.
   cdef cppclass optional_frame_id_t "std::optional<memray::tracking_api::frame_id_t>":
       pass
