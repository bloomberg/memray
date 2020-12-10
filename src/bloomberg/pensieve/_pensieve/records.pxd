from libcpp.string cimport string
from libcpp.vector cimport vector

cdef extern from "records.h" namespace "pensieve::tracking_api":

   struct PyFrame:
       string function_name
       string filename
       int lineno

   struct PyAllocationRecord:
       long int pid
       long int tid
       unsigned long address
       size_t size
       string allocator
       vector[PyFrame] stack_trace
