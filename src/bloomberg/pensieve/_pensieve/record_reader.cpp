#include "record_reader.h"
#include "records.h"

#include "Python.h"

#include <deque>
#include <sstream>

namespace pensieve::api {

using namespace tracking_api;

StackTraceTree::index_t
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
}

void
RecordReader::parseFrameIndex()
{
    tracking_api::pyframe_map_val_t pyframe_val;
    d_input.read((char*)&pyframe_val.first, sizeof(pyframe_val.first));
    std::getline(d_input, pyframe_val.second.function_name, '\0');
    std::getline(d_input, pyframe_val.second.filename, '\0');
    d_input.read((char*)&pyframe_val.second.lineno, sizeof(pyframe_val.second.lineno));
    auto iterator = d_frame_map.insert(pyframe_val);
    if (!iterator.second) {
        throw std::runtime_error("Two entries with the same ID found!");
    }
}

PyObject*
RecordReader::nextAllocation()
{
    if (d_input.peek() == EOF) {
        PyErr_SetString(PyExc_StopIteration, "No more data to read");
        return nullptr;
    }

    while (d_input.peek() != EOF) {
        RecordType record_type;
        d_input.read(reinterpret_cast<char*>(&record_type), sizeof(RecordType));
        switch (record_type) {
            case RecordType::ALLOCATION:
                return parseAllocation();
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

void
RecordReader::parseFrame()
{
    FrameSeqEntry frame_seq_entry{};
    d_input.read(reinterpret_cast<char*>(&frame_seq_entry), sizeof(FrameSeqEntry));
    thread_id_t tid = frame_seq_entry.tid;

    auto isCoherentPop = [&](const auto& stack_traces, const auto& frame_entry) {
        frame_id_t prev_frame_id = stack_traces.at(frame_entry.tid).front();
        return getFrameKey(frame_entry.frame_id) == getFrameKey(prev_frame_id);
    };

    switch (frame_seq_entry.action) {
        case PUSH:
            stack_traces[tid].push_front(frame_seq_entry.frame_id);
            break;
        case POP:
            if (isCoherentPop(stack_traces, frame_seq_entry)) {
                stack_traces[tid].pop_front();
            }
            break;
    }
}

PyObject*
RecordReader::parseAllocation()
{
    AllocationRecord record{};
    d_input.read(reinterpret_cast<char*>(&record), sizeof(AllocationRecord));

    StackTraceTree::index_t index = 0;
    const auto stack = d_stack_traces.find(record.tid);
    if (stack != d_stack_traces.end()) {
        index = d_tree.getTraceIndex(stack->second);
    }

    // We are not using PyBuildValue here because unrolling the
    // operations speeds up the parsing moderately. Additionally, some of
    // the types we need to convert from are not supported by PyBuildValue
    // natively.
    PyObject* tuple = PyTuple_New(5);
    if (tuple == nullptr) {
        return nullptr;
    }

#define __CHECK_ERROR(elem)                                                                             \
    do {                                                                                                \
        if (elem == nullptr) {                                                                          \
            Py_DECREF(tuple);                                                                           \
            return nullptr;                                                                             \
        }                                                                                               \
    } while (0)
    PyObject* elem = PyLong_FromLong(record.tid);
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 0, elem);
    elem = PyLong_FromUnsignedLong(record.address);
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 1, elem);
    elem = PyLong_FromSize_t(record.size);
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 2, elem);
    elem = PyLong_FromLong(static_cast<int>(record.allocator));
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 3, elem);
    elem = PyLong_FromUnsignedLong(index);
    __CHECK_ERROR(elem);
    PyTuple_SET_ITEM(tuple, 4, elem);
#undef __CHECK_ERROR

    return tuple;
}

PyObject*
RecordReader::get_stack_frame(const StackTraceTree::index_t index, const size_t max_stacks) const
{
    size_t stacks_obtained = 0;
    StackTraceTree::index_t current_index = index;
    PyObject* list = PyList_New(0);
    if (list == nullptr) {
        return nullptr;
    }

    while (current_index != 0 && ++stacks_obtained != max_stacks) {
        auto node = d_tree.nextNode(current_index);
        const auto& frame = d_frame_map.at(node.frame_id);
        PyObject* tuple = Py_BuildValue(
                "(ssi)",
                frame.function_name.c_str(),
                frame.filename.c_str(),
                frame.lineno);
        if (tuple == nullptr) {
            goto error;
        }
        if (PyList_Append(list, tuple) != 0) {
            Py_DECREF(tuple);
            goto error;
        }
        current_index = node.parent_index;
    }
    return list;
error:
    Py_XDECREF(list);
    return nullptr;
}

}  // namespace pensieve::api
