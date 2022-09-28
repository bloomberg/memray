cdef extern from "<algorithm>" namespace "std" nogil:
    ssize_t count[Iter, T](Iter first, Iter last, const T& value)
