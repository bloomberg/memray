#pragma once

#include <iostream>
#include <ostream>
#include <vector>

namespace pensieve::tracking_api {

/**
 * Track record of a Python frame in the Python native stack.
 *
 * The purpose of this class is to be a lightweight reference to an element of the Python stack that we
 * can read without the GIL held. All the information that requires the GIL to be acquired in the
 * Python frame that this struct represents is already transformed into native types that can be
 * accessed directly. The lifetime of pointers and references is directly linked to the frame object
 * this record represents, so the pointers are not valid once the frame is deallocated. The trace
 * function should remove these elements from the container where they live as frames are pop-ed from
 * the stack.
 *
 **/
struct PyFrameRecord
{
    const char* function_name;
    const char* filename;
    int lineno;

    friend std::ostream& operator<<(std::ostream& os, const PyFrameRecord& frame);
};

std::ostream&
operator<<(std::ostream& os, const PyFrameRecord& frame);

struct Frame
{
    explicit Frame(PyFrameRecord& pyframe);
    std::string function_name;
    std::string filename;
    int lineno;
};
struct AllocationRecord
{
    pid_t pid;
    long int tid;
    unsigned long address;
    size_t size;
    std::vector<Frame> stacktrace;
    std::string allocator;
};

}  // namespace pensieve::tracking_api