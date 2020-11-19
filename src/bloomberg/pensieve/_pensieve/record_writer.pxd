from _pensieve.records cimport AllocationRecord

cdef extern from "record_writer.h" namespace "pensieve::api":
    cdef cppclass Serializer:
        void write(const AllocationRecord& record)
        void close()

    cdef cppclass InMemorySerializer(Serializer):
        InMemorySerializer()
        void write(const AllocationRecord& record)
        void close()
