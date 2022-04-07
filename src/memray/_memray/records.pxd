from libc.stdint cimport uintptr_t
from libcpp cimport bool
from libcpp.string cimport string
from libcpp.vector cimport vector


cdef extern from "records.h" namespace "memray::tracking_api":

   struct Frame:
       string function_name
       string filename
       int lineno

   struct AllocationRecord:
       long int tid
       uintptr_t address
       size_t size
       string allocator
       vector[Frame] stack_trace

   struct TrackerStats:
       size_t n_allocations
       size_t n_frames
       long long start_time
       long long end_time

   struct HeaderRecord:
       int version
       bool native_traces
       TrackerStats stats
       string command_line
       int pid
       int python_allocator

   cdef cppclass Allocation:
       AllocationRecord record
       size_t frame_index
       size_t n_allocations
       object toPythonObject()

   struct MemoryRecord:
       unsigned long int ms_since_epoch
       size_t rss
