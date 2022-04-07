cdef extern from "logging.h" namespace "memray":
    void setLogThreshold(int)
