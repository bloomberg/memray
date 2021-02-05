from libc.stdint cimport uintptr_t
from libcpp.string cimport string
from libcpp.vector cimport vector
cdef extern from "records.h" namespace "pensieve::tracking_api":

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

   cdef cppclass Allocation:
       AllocationRecord record
       size_t frame_index
       size_t n_allocactions
       object toPythonObject()

