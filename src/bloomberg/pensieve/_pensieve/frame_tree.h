#pragma once
#include <vector>

#include "records.h"

namespace pensieve::tracking_api {
class FrameTree
{
  public:
    using index_t = uint32_t;
    struct FrameNode
    {
        frame_id_t frame_id;
        index_t parent_index;
    };

    inline const FrameNode& nextNode(index_t index) const
    {
        assert(1 <= index && index <= d_graph.size());
        return d_graph[index - 1];
    }

    using tracecallback_t = std::function<bool(frame_id_t, index_t)>;

    template<typename T>
    size_t getTraceIndex(const T& stack_trace)
    {
        return getTraceIndex(stack_trace, [](frame_id_t, index_t) { return true; });
    }

    template<typename T>
    size_t getTraceIndex(const T& stack_trace, const tracecallback_t& callback)
    {
        index_t index = 0;
        FrameEdge* parent = &d_root;
        for (auto frame_it = stack_trace.begin(); frame_it < stack_trace.end(); ++frame_it) {
            auto frame = *frame_it;
            auto it = std::lower_bound(
                    parent->children.begin(),
                    parent->children.end(),
                    frame,
                    [](const FrameEdge& edge, const tracking_api::frame_id_t frame_id) {
                        return edge.frame_id < frame_id;
                    });
            if (it == parent->children.end() || it->frame_id != frame) {
                index_t new_index = d_current_tree_index++;
                it = parent->children.insert(it, {frame, new_index, {}});
                if (!callback(frame, parent->index)) {
                    return 0;
                }
                d_graph.push_back({frame, parent->index});
            }
            index = it->index;
            parent = &(*it);
        }
        return index;
    }

  private:
    struct FrameEdge
    {
        frame_id_t frame_id;
        index_t index;
        std::vector<FrameEdge> children;
    };
    FrameEdge d_root = {0, 0, {}};
    size_t d_current_tree_index = 1;
    std::vector<FrameNode> d_graph{};
};
}  // namespace pensieve::tracking_api