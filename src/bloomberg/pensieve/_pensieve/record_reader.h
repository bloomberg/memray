#pragma once

#include <fstream>
#include <functional>
#include <memory>
#include <unordered_map>

#include "record_reader.h"
#include "records.h"

namespace pensieve::api {

class StackTraceTree
{
  public:
    using index_t = uint32_t;
    struct Node
    {
        tracking_api::frame_id_t frame_id;
        index_t parent_index;
    };

    inline const Node& nextNode(index_t index) const
    {
        assert(1 <= index && index <= d_graph.size());
        return d_graph[index - 1];
    }

    index_t getTraceIndex(const std::vector<tracking_api::frame_id_t>& stack_trace);

  private:
    struct NodeEdge
    {
        tracking_api::frame_id_t frame_id;
        index_t index;
        std::vector<NodeEdge> children;
    };
    NodeEdge d_root = {0, 0, {}};
    index_t d_current_tree_index = 1;
    std::vector<Node> d_graph{};
};

class PyUnicode_Cache
{
  public:
    PyObject* getUnicodeObject(const std::string& str);

  private:
    using py_capsule_t = std::unique_ptr<PyObject, std::function<void(PyObject*)>>;
    std::unordered_map<std::string, py_capsule_t> d_cache{};
};

class RecordReader
{
  public:
    explicit RecordReader(const std::string& file_name);
    PyObject* nextAllocation();
    PyObject* get_stack_frame(StackTraceTree::index_t index, size_t max_stacks = 0) const;

  private:
    // Aliases
    using stack_traces_t =
            std::unordered_map<tracking_api::thread_id_t, std::vector<tracking_api::frame_id_t>>;

    // Data members
    std::ifstream d_input;
    tracking_api::pyframe_map_t d_frame_map{};
    stack_traces_t d_stack_traces{};
    StackTraceTree d_tree{};
    mutable PyUnicode_Cache d_pystring_cache{};

    // Methods
    PyObject* parseAllocation();
    void parseFrame();
    void parseFrameIndex();
};

}  // namespace pensieve::api
