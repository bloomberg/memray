from libcpp.vector cimport vector
from libcpp.string cimport string

from _pensieve.records cimport AllocationRecord

cdef extern from "tracking_api.h" namespace "pensieve::tracking_api":
   const vector[AllocationRecord] get_allocation_records()

   void install_trace_function() except*


cdef extern from "tracking_api.h" namespace "pensieve::api":
    void attach_init() except*
    void attach_fini() except*
