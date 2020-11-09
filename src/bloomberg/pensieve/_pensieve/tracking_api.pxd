from libcpp.vector cimport vector
from libcpp.string cimport string

cdef extern from "tracking_api.h" namespace "pensieve::tracking_api":
   struct Frame:
       string function_name
       string filename
       int lineno
   struct AllocationRecord:
       long int pid
       long int tid
       unsigned long address
       size_t size
       vector[Frame] stacktrace
       string allocator
   const vector[AllocationRecord] get_allocation_records()

   void install_trace_function() except*


cdef extern from "tracking_api.h" namespace "pensieve::api":
    void attach_init() except*
    void attach_fini() except*
