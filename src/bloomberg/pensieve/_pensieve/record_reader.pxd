from libcpp.string cimport string
from libcpp.vector cimport vector

from _pensieve.records cimport PyAllocationRecord as AllocationRecord

cdef extern from "record_reader.h" namespace "pensieve::api":
    cdef cppclass RecordReader:
        RecordReader(const string& file_name)
        vector[AllocationRecord] results()
