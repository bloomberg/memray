#pragma once
#include "Python.h"
#include "records.h"
#include <iostream>
#include <vector>

namespace memray::tracking_api {
class FrameTree
{
  public:
    using index_t = uint32_t;  // TODO: Shouldn't this be size_t?

    inline index_t minIndex() const
    {
        return 1;
    }

    inline index_t maxIndex() const
    {
        return d_graph.size() - 1;
    }

    inline std::pair<frame_id_t, index_t> nextNode(index_t index) const
    {
        assert(1 <= index && index <= d_graph.size() - 1);
        return std::make_pair(d_graph[index].frame_id, d_graph[index].parent_index);
    }

    using tracecallback_t = std::function<bool(frame_id_t, index_t)>;

    template<typename T>
    size_t getTraceIndex(const T& stack_trace, const tracecallback_t& callback)
    {
        index_t index = 0;
        for (const auto& frame : stack_trace) {
            index = getTraceIndexUnsafe(index, frame, callback);
        }
        return index;
    }

    size_t getTraceIndex(index_t parent_index, frame_id_t frame)
    {
        return getTraceIndexUnsafe(parent_index, frame, tracecallback_t());
    }

  private:
    size_t getTraceIndexUnsafe(index_t parent_index, frame_id_t frame, const tracecallback_t& callback)
    {
        Node& parent = d_graph[parent_index];
        auto it = std::lower_bound(parent.children.begin(), parent.children.end(), frame);
        if (it == parent.children.end() || it->frame_id != frame) {
            index_t new_index = d_graph.size();
            it = parent.children.insert(it, {frame, new_index});
            if (callback && !callback(frame, parent_index)) {
                return 0;
            }
            d_graph.push_back({frame, parent_index});
        }
        return it->child_index;
    }

    struct DescendentEdge
    {
        frame_id_t frame_id;
        index_t child_index;

        bool operator<(frame_id_t the_frame_id) const
        {
            return this->frame_id < the_frame_id;
        }
    };

    struct Node
    {
        frame_id_t frame_id;
        index_t parent_index;
        std::vector<DescendentEdge> children;
    };
    std::vector<Node> d_graph{{0, 0, {}}};

  public:
    PyObject* Py_GetGraphTree()
    {
        PyObject* tree_nodes = PyList_New(0);
        if (tree_nodes == nullptr) {
            PyErr_SetString(PyExc_RuntimeError, "tree_nodes is nullptr");
            return nullptr;
        }
        for (const auto& node : d_graph) {
            PyObject* result = PyList_New(0);  // 创建一个元组，包含三个元素
            if (result == nullptr) {
                PyErr_SetString(PyExc_RuntimeError, "node tuple is nullptr");
                return nullptr;
            }

            // 将 Node 结构的字段添加为元组的元素
            PyObject* a = PyLong_FromUnsignedLong(node.frame_id);
            PyObject* b = PyLong_FromUnsignedLong(node.parent_index);
            PyList_Append(result, a);
            PyList_Append(result, b);
            Py_XDECREF(a);
            Py_XDECREF(b);

            PyObject* children_list = PyList_New(0);
            if (children_list == nullptr) {
                PyErr_SetString(PyExc_RuntimeError, "children list is nullptr");
                return nullptr;
            }
            for (size_t i = 0; i < node.children.size(); ++i) {
                const DescendentEdge& edge = node.children[i];
                PyObject* pfid = PyLong_FromUnsignedLong(edge.frame_id);
                PyObject* pchild = PyLong_FromLong(edge.child_index);
                PyObject* child_tuple = PyTuple_Pack(2, pfid, pchild);
                Py_XDECREF(pfid);
                Py_XDECREF(pchild);
                int ret = PyList_Append(children_list, child_tuple);
                Py_XDECREF(child_tuple);
                if (ret != 0) {
                    goto frame_error;
                }
            }
            PyList_Append(result, children_list);
            Py_XDECREF(children_list);

            int ret = PyList_Append(tree_nodes, result);
            Py_XDECREF(result);
            if (ret != 0) {
                goto frame_error;
            }
        }
        return tree_nodes;
frame_error:
        Py_XDECREF(tree_nodes);
        return nullptr;
    }
};
}  // namespace memray::tracking_api
