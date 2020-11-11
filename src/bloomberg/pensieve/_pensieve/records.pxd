from libcpp.vector cimport vector
from libcpp.string cimport string

cdef extern from "records.h" namespace "pensieve::tracking_api":
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
