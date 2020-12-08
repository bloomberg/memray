#pragma once

#include <Python.h>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <ostream>
#include <vector>

namespace pensieve::tracking_api {

const char TOKEN_ALLOCATION = 'a';
const char TOKEN_FRAME_INDEX = 'i';
const char TOKEN_FRAME = 'f';

typedef size_t frame_id_t;

struct Frame
{
    const char* function_name;
    const char* filename;
    int lineno;
};

struct PyFrame
{
    std::string function_name;
    std::string filename;
    int lineno;
};

enum FrameAction { PUSH, POP };

struct AllocationRecord
{
    pid_t pid;
    long int tid;
    unsigned long address;
    size_t size;
    std::string allocator;
    std::vector<frame_id_t> stack_trace;  // TODO remove this vector
};

struct PyAllocationRecord
{
    pid_t pid;
    long int tid;
    unsigned long address;
    size_t size;
    std::string allocator;
    std::vector<PyFrame> stack_trace;
};

typedef std::pair<frame_id_t, Frame> frame_key_t;
typedef std::unordered_map<frame_key_t::first_type, frame_key_t::second_type> frame_map_t;

typedef std::pair<frame_id_t, PyFrame> pyframe_map_val_t;
typedef std::unordered_map<pyframe_map_val_t::first_type, pyframe_map_val_t::second_type> pyframe_map_t;

typedef std::pair<frame_id_t, FrameAction> frame_seq_pair_t;

/**
 * Stream operators.
 */
std::ostream&
operator<<(std::ostream&, const PyFrame&);
std::istream&
operator>>(std::istream&, PyFrame&);

std::ostream&
operator<<(std::ostream&, const AllocationRecord&);
std::istream&
operator>>(std::istream&, AllocationRecord&);

std::ostream&
operator<<(std::ostream&, const frame_seq_pair_t&);
std::istream&
operator>>(std::istream&, frame_seq_pair_t&);

std::ostream&
operator<<(std::ostream&, const frame_map_t&);
std::istream&
operator>>(std::istream&, std::pair<frame_id_t, PyFrame>&);

/**
 * Utility functions.
 */
frame_id_t
add_frame(frame_map_t& frame_map, const Frame& frame);

size_t
str_hash(const char* val);

}  // namespace pensieve::tracking_api

namespace {
/**
 * Custom hash function to uniquely identify frames based on the function, file and line number.
 *
 * See https://stackoverflow.com/a/38140932.
 */
inline void
hash_combine([[maybe_unused]] std::size_t& seed)
{
}

template<typename T, typename... Rest>
inline void
hash_combine(std::size_t& seed, const T& v, Rest... rest)
{
    std::hash<T> hasher;
    seed ^= hasher(v) + 0x9e3779b9 + (seed << 6) + (seed >> 2);
    hash_combine(seed, rest...);
}

}  // anonymous namespace
