#pragma once

#include <Python.h>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <ostream>
#include <pthread.h>
#include <vector>

#include <hooks.h>

namespace pensieve::tracking_api {

enum class RecordType {
    ALLOCATION = 1,
    FRAME_INDEX = 2,
    FRAME = 3,
};

typedef size_t frame_id_t;
typedef long unsigned int thread_id_t;

struct RawFrame
{
    const char* function_name;
    const char* filename;
    unsigned long lineno;
};

struct Frame
{
    std::string function_name;
    std::string filename;
    unsigned long lineno;
};

struct RawAllocationRecord
{
    thread_id_t tid;
    unsigned long address;
    size_t size;
    hooks::Allocator allocator;
};

struct AllocationRecord
{
    thread_id_t tid;
    unsigned long address;
    size_t size;
    std::string allocator;
    std::vector<Frame> stack_trace;
};

enum FrameAction { PUSH, POP };

struct FrameSeqEntry
{
    frame_id_t frame_id;
    thread_id_t tid;
    FrameAction action;
};

typedef std::pair<frame_id_t, RawFrame> frame_key_t;
typedef std::unordered_map<frame_key_t::first_type, frame_key_t::second_type> frame_map_t;

typedef std::pair<frame_id_t, Frame> pyframe_map_val_t;
typedef std::unordered_map<pyframe_map_val_t::first_type, pyframe_map_val_t::second_type> pyframe_map_t;

/**
 * Utility functions.
 */
frame_id_t
add_frame(frame_map_t& frame_map, const RawFrame& frame);

size_t
str_hash(const char* val);

}  // namespace pensieve::tracking_api
