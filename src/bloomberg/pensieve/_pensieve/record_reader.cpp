#include <algorithm>
#include <cstdio>
#include <stdexcept>

#include "Python.h"

#include "hooks.h"
#include "logging.h"
#include "record_reader.h"
#include "records.h"

namespace pensieve::api {

using namespace tracking_api;

/**
 * Produce an aggregated snapshot from a vector of allocations and a index in that vector
 *
 * This function takes a vector containing a sequence of allocation events and an index in that
 * vector indicating the position where the snapshot should be produced and returns a collection
 * of allocations representing the heap structure at that particular point. This collection of
 * allocations is aggregated so allocations with the same stack trace will be reported together
 * as a single allocation with the size being the sum af the sizes of the individual allocations.
 *
 **/
static reduced_snapshot_map_t
reduceSnapshotAllocations(const allocations_t& records, size_t snapshot_index)
{
    assert(snapshot_index < records.size());

    std::unordered_map<unsigned long, size_t> ptr_to_allocation{};
    const auto snapshot_limit = records.cbegin() + snapshot_index;
    for (auto record_it = records.cbegin(); record_it <= snapshot_limit; record_it++) {
        switch (record_it->record.allocator) {
            case hooks::Allocator::FREE:
            case hooks::Allocator::MUNMAP: {
                auto it = ptr_to_allocation.find(record_it->record.address);
                if (it != ptr_to_allocation.end()) {
                    ptr_to_allocation.erase(it);
                }
                break;
            }
            case hooks::Allocator::CALLOC:
            case hooks::Allocator::MALLOC:
            case hooks::Allocator::MEMALIGN:
            case hooks::Allocator::MMAP:
            case hooks::Allocator::POSIX_MEMALIGN:
            case hooks::Allocator::PVALLOC:
            case hooks::Allocator::REALLOC:
            case hooks::Allocator::VALLOC: {
                ptr_to_allocation[record_it->record.address] = record_it - records.begin();
                break;
            }
        }
    }

    std::unordered_map<StackTraceTree::index_t, Allocation> stack_to_allocation{};
    for (const auto& it : ptr_to_allocation) {
        const auto& record = records[it.second];
        auto alloc_it = stack_to_allocation.find(record.frame_index);
        if (alloc_it == stack_to_allocation.end()) {
            stack_to_allocation.insert(alloc_it, std::pair(record.frame_index, record));
        } else {
            alloc_it->second.record.size += record.record.size;
            alloc_it->second.n_allocactions += 1;
        }
    }
    return stack_to_allocation;
}

static size_t
getHighWatermarkIndex(const allocations_t& records)
{
    size_t current_memory = 0;
    size_t max_memory = 0;
    size_t high_water_mark_index = 0;
    std::unordered_map<unsigned long, size_t> ptr_to_allocation{};

    for (auto records_it = records.cbegin(); records_it != records.cend(); records_it++) {
        switch (records_it->record.allocator) {
            // TODO: Add the rest of allocators (also let's talk first about REALLOC).
            case hooks::Allocator::FREE:
            case hooks::Allocator::MUNMAP: {
                auto it = ptr_to_allocation.find(records_it->record.address);
                if (it != ptr_to_allocation.end()) {
                    current_memory -= records[it->second].record.size;
                    ptr_to_allocation.erase(it);
                }
                break;
            }
            case hooks::Allocator::CALLOC:
            case hooks::Allocator::MALLOC:
            case hooks::Allocator::MEMALIGN:
            case hooks::Allocator::MMAP:
            case hooks::Allocator::POSIX_MEMALIGN:
            case hooks::Allocator::PVALLOC:
            case hooks::Allocator::REALLOC:
            case hooks::Allocator::VALLOC: {
                current_memory += records_it->record.size;
                if (current_memory >= max_memory) {
                    high_water_mark_index = records_it - records.cbegin();
                    max_memory = current_memory;
                }
                ptr_to_allocation[records_it->record.address] = records_it - records.begin();
                break;
            }
        }
    }
    return high_water_mark_index;
}

size_t
StackTraceTree::getTraceIndex(const std::vector<tracking_api::frame_id_t>& stack_trace)
{
    index_t index = 0;
    NodeEdge* parent = &d_root;
    for (auto frame_it = stack_trace.cbegin(); frame_it < stack_trace.cend(); ++frame_it) {
        auto frame = *frame_it;
        auto it = std::lower_bound(
                parent->children.begin(),
                parent->children.end(),
                frame,
                [](const NodeEdge& edge, const tracking_api::frame_id_t frame_id) {
                    return edge.frame_id < frame_id;
                });
        if (it == parent->children.end() || it->frame_id != frame) {
            index_t new_index = d_current_tree_index++;
            it = parent->children.insert(it, {frame, new_index, {}});
            d_graph.push_back({frame, parent->index});
        }
        index = it->index;
        parent = &(*it);
    }
    return index;
}

RecordReader::RecordReader(const std::string& file_name)
{
    d_input.open(file_name, std::ios::binary | std::ios::in);
    d_input.read(reinterpret_cast<char*>(&d_header), sizeof(d_header));
    d_allocation_frames = tracking_api::FrameCollection<tracking_api::Frame>(d_header.stats.n_frames);
}

void
RecordReader::parseFrame()
{
    FrameSeqEntry frame_seq_entry{};
    d_input.read(reinterpret_cast<char*>(&frame_seq_entry), sizeof(FrameSeqEntry));
    thread_id_t tid = frame_seq_entry.tid;

    switch (frame_seq_entry.action) {
        case PUSH:
            d_stack_traces[tid].push_back(frame_seq_entry.frame_id);
            break;
        case POP:
            d_stack_traces[tid].pop_back();
            break;
    }
}

void
RecordReader::parseFrameIndex()
{
    tracking_api::pyframe_map_val_t pyframe_val;
    d_input.read(reinterpret_cast<char*>(&pyframe_val.first), sizeof(pyframe_val.first));
    std::getline(d_input, pyframe_val.second.function_name, '\0');
    std::getline(d_input, pyframe_val.second.filename, '\0');
    d_input.read(
            reinterpret_cast<char*>(&pyframe_val.second.parent_lineno),
            sizeof(pyframe_val.second.parent_lineno));
    auto iterator = d_frame_map.insert(pyframe_val);
    if (!iterator.second) {
        throw std::runtime_error("Two entries with the same ID found!");
    }
}

AllocationRecord
RecordReader::parseAllocationRecord()
{
    AllocationRecord record{};
    d_input.read(reinterpret_cast<char*>(&record), sizeof(AllocationRecord));
    return record;
}

RecordReader::allocations_t
RecordReader::parseAllocations()
{
    RecordReader::allocations_t records;
    while (d_input.peek() != EOF) {
        RecordType record_type;
        d_input.read(reinterpret_cast<char*>(&record_type), sizeof(RecordType));
        switch (record_type) {
            case RecordType::ALLOCATION: {
                AllocationRecord record = parseAllocationRecord();
                size_t f_index = getAllocationFrameIndex(record);
                records.emplace_back(Allocation{record, f_index});
                break;
            }
            case RecordType::FRAME:
                parseFrame();
                break;
            case RecordType::FRAME_INDEX:
                parseFrameIndex();
                break;
            default:
                throw std::runtime_error("Invalid record type");
        }
    }
    return records;
}

size_t
RecordReader::getAllocationFrameIndex(const AllocationRecord& record)
{
    auto stack = d_stack_traces.find(record.tid);
    if (stack == d_stack_traces.end()) {
        return 0;
    }
    correctAllocationFrame(stack->second, record.py_lineno);
    return d_tree.getTraceIndex(stack->second);
}

void
RecordReader::correctAllocationFrame(stack_t& stack, int lineno)
{
    if (stack.empty()) {
        return;
    }
    const Frame& partial_frame = d_frame_map.at(stack.back());
    Frame allocation_frame{
            partial_frame.function_name,
            partial_frame.filename,
            partial_frame.parent_lineno,
            lineno};
    auto [allocation_index, is_new_frame] = d_allocation_frames.getIndex(allocation_frame);
    if (is_new_frame) {
        d_frame_map.emplace(allocation_index, allocation_frame);
    }
    stack.back() = allocation_index;
}

// Python public APIs

PyObject*
RecordReader::Py_NextAllocationRecord()
{
    if (d_input.peek() == EOF) {
        PyErr_SetString(PyExc_StopIteration, "No more data to read");
        return nullptr;
    }

    while (d_input.peek() != EOF) {
        RecordType record_type;
        d_input.read(reinterpret_cast<char*>(&record_type), sizeof(RecordType));
        switch (record_type) {
            case RecordType::ALLOCATION: {
                AllocationRecord record = parseAllocationRecord();
                size_t f_index = getAllocationFrameIndex(record);
                return Allocation{record, f_index}.toPythonObject();
            }
            case RecordType::FRAME:
                parseFrame();
                break;
            case RecordType::FRAME_INDEX:
                parseFrameIndex();
                break;
            default:
                throw std::runtime_error("Invalid record type");
        }
    }

    PyErr_SetString(PyExc_StopIteration, "No more data to read");
    return nullptr;
}

PyObject*
RecordReader::Py_HighWatermarkAllocationRecords()
{
    if (d_input.peek() == EOF) {
        PyErr_SetString(PyExc_StopIteration, "No more data to read");
        return nullptr;
    }

    LOG(DEBUG) << "Parsing file";

    auto all_records = parseAllocations();

    if (all_records.empty()) {
        return PyList_New(0);
    }

    LOG(DEBUG) << "Computing high watermark index";

    auto high_watermark_index = getHighWatermarkIndex(all_records);

    LOG(DEBUG) << "Preparing snapshot for high watermark index";

    const auto stack_to_allocation = reduceSnapshotAllocations(all_records, high_watermark_index);

    LOG(DEBUG) << "Converting data to Python objects";

    PyObject* list = PyList_New(stack_to_allocation.size());
    if (list == nullptr) {
        return nullptr;
    }
    size_t list_index = 0;
    for (const auto& it : stack_to_allocation) {
        const auto& record = it.second;
        PyObject* pyrecord = record.toPythonObject();
        if (pyrecord == nullptr) {
            Py_DECREF(list);
            return nullptr;
        }
        PyList_SET_ITEM(list, list_index++, pyrecord);
    }
    return list;
}

PyObject*
RecordReader::Py_GetStackFrame(unsigned int index, size_t max_stacks)
{
    size_t stacks_obtained = 0;
    StackTraceTree::index_t current_index = index;
    PyObject* list = PyList_New(0);
    if (list == nullptr) {
        return nullptr;
    }

    int current_lineno = -1;
    while (current_index != 0 && ++stacks_obtained != max_stacks) {
        auto node = d_tree.nextNode(current_index);
        const auto& frame = d_frame_map.at(node.frame_id);
        PyObject* pyframe = frame.toPythonObject(d_pystring_cache, current_lineno);
        if (pyframe == nullptr) {
            return nullptr;
        }
        if (PyList_Append(list, pyframe) != 0) {
            Py_DECREF(pyframe);
            goto error;
        }
        current_index = node.parent_index;
        current_lineno = frame.parent_lineno;
    }
    return list;
error:
    Py_XDECREF(list);
    return nullptr;
}
size_t
RecordReader::totalAllocations() const noexcept
{
    return d_header.stats.n_allocations;
}

size_t
RecordReader::totalFrames() const noexcept
{
    return d_header.stats.n_frames;
}

}  // namespace pensieve::api
