#pragma once

#include <functional>
#include <map>
#include <optional>
#include <set>
#include <unordered_map>
#include <vector>

#include "Python.h"

#include "frame_tree.h"
#include "records.h"

namespace memray::api {

using namespace tracking_api;

const thread_id_t NO_THREAD_INFO = 0;

struct index_thread_pair_hash
{
    std::size_t operator()(const std::pair<FrameTree::index_t, thread_id_t>& p) const
    {
        // The indices and thread IDs are not likely to match as they are fundamentally different
        // values and have different ranges, so xor should work here and not cause duplicate hashes.
        return std::hash<FrameTree::index_t>{}(p.first) xor std::hash<thread_id_t>{}(p.second);
    }
};

using allocations_t = std::vector<Allocation>;
using reduced_snapshot_map_t = std::
        unordered_map<std::pair<FrameTree::index_t, thread_id_t>, Allocation, index_thread_pair_hash>;

struct Interval
{
    Interval(uintptr_t begin, uintptr_t end);
    [[nodiscard]] std::optional<Interval> intersection(const Interval& other) const;
    [[nodiscard]] bool leftIntersects(const Interval& other) const;
    [[nodiscard]] bool rightIntersects(const Interval& other) const;
    [[nodiscard]] size_t size() const;

    bool operator==(const Interval& rhs) const;
    bool operator!=(const Interval& rhs) const;

    uintptr_t begin;
    uintptr_t end;
};

template<typename T>
class IntervalTree
{
  private:
    using intervals_t = std::vector<std::pair<Interval, T>>;
    intervals_t d_intervals;

  public:
    using const_iterator = typename intervals_t::const_iterator;
    using iterator = typename intervals_t::iterator;

    void addInterval(uintptr_t start, size_t size, const T& element)
    {
        if (size <= 0) {
            return;
        }
        d_intervals.emplace_back(Interval(start, start + size), element);
    }
    std::optional<std::vector<std::pair<Interval, T>>> removeInterval(uintptr_t start, size_t size)
    {
        if (size <= 0) {
            return std::nullopt;
        }

        std::vector<std::pair<Interval, T>> new_intervals;
        std::vector<std::pair<Interval, T>> removed_intervals;
        const auto removed_interval = Interval(start, start + size);

        for (auto& [interval, value] : d_intervals) {
            std::optional<Interval> intersection = interval.intersection(removed_interval);
            // This interval doesn't contain the element to remove, so don't remove
            // anything
            if (!intersection) {
                new_intervals.emplace_back(interval, value);
                continue;
            }
            // The interval completely overlaps with the interval that we got, so we need to
            // remove it entirely: add it to the list of removed intervals.
            if ((intersection == interval)) {
                removed_intervals.emplace_back(intersection.value(), value);
            }
            // Check if the interval intersects from the left and then remove a piece from the start.
            else if (intersection->leftIntersects(interval))
            {
                auto new_interval = Interval{intersection->end, interval.end};
                new_intervals.emplace_back(new_interval, value);
                removed_intervals.emplace_back(intersection.value(), value);
            }
            // Check if the interval intersects from the right and then remove a piece from the start.
            else if (intersection->rightIntersects(interval))
            {
                auto new_interval = Interval{interval.begin, intersection->begin};
                new_intervals.emplace_back(new_interval, value);
                removed_intervals.emplace_back(intersection.value(), value);
            }
            // The interval is contained in the chunk, so we need to remove the intersection from the
            // middle, effectively splitting the interval in two.
            else
            {
                new_intervals.emplace_back(Interval{interval.begin, intersection->begin}, value);
                new_intervals.emplace_back(Interval{intersection->end, interval.end}, value);
                removed_intervals.emplace_back(intersection.value(), value);
            }
        }

        // Re-assign intervals after the calculation.
        d_intervals = new_intervals;

        if (removed_intervals.empty()) {
            return std::nullopt;
        }
        return removed_intervals;
    }

    std::vector<Interval> findIntersection(uintptr_t start, size_t size)
    {
        std::vector<Interval> ret;
        const auto needle = Interval(start, start + size);
        for (auto& [interval, _] : d_intervals) {
            std::optional<Interval> intersection = interval.intersection(needle);
            if (intersection) {
                ret.push_back(intersection.value());
            }
        }

        return ret;
    }

    size_t size() const
    {
        size_t result = 0;
        std::for_each(d_intervals.begin(), d_intervals.end(), [&](const auto& pair) {
            result += pair.first.size();
        });
        return result;
    }

    void clear()
    {
        d_intervals.clear();
    }

    iterator begin()
    {
        return d_intervals.begin();
    }

    iterator end()
    {
        return d_intervals.end();
    }

    const_iterator begin() const
    {
        return d_intervals.begin();
    }

    const_iterator end() const
    {
        return d_intervals.end();
    }

    const_iterator cbegin() const
    {
        return d_intervals.cbegin();
    }

    const_iterator cend() const
    {
        return d_intervals.cend();
    }
};

class SnapshotAllocationAggregator
{
  private:
    IntervalTree<Allocation> d_interval_tree;
    std::unordered_map<uintptr_t, Allocation> d_ptr_to_allocation{};

  public:
    void addAllocation(const Allocation& allocation);
    reduced_snapshot_map_t getSnapshotAllocations(bool merge_threads);
};

struct HighWaterMark
{
    size_t index{0};
    size_t peak_memory{0};
};

class StreamingAllocationAggregator
{
  private:
    size_t d_high_water_mark_index{0};
    size_t d_high_water_mark_memory{0};
    size_t d_allocations_seen{0};

    IntervalTree<Allocation> d_high_water_mark_ranges;
    std::unordered_map<uintptr_t, Allocation> d_high_water_mark_ptrs;

    size_t d_delta_freed_size{0};
    IntervalTree<int> d_delta_freed_ranges;
    std::set<uintptr_t> d_delta_freed_ptrs{};

    size_t d_delta_allocated_size{0};
    IntervalTree<Allocation> d_delta_allocated_ranges;
    std::map<uintptr_t, Allocation> d_delta_allocated_ptrs{};

    bool atHighWaterMark() const;
    void applyDeltaToSnapshot(
            IntervalTree<Allocation>* allocated_ranges,
            std::unordered_map<uintptr_t, Allocation>* allocated_ptrs);
    void resetDelta();
    void addAllocationWhileAtHighWaterMark(const Allocation& allocation);
    void addAllocationWhileNotAtHighWaterMark(const Allocation& allocation);

  public:
    void addAllocation(const Allocation& allocation);
    reduced_snapshot_map_t getHighWaterMarkAllocations(bool merge_threads);
    reduced_snapshot_map_t getLeakedAllocations(bool merge_threads);
    HighWaterMark getHighWaterMark() const noexcept;
};

PyObject*
Py_ListFromSnapshotAllocationRecords(const reduced_snapshot_map_t& stack_to_allocation);

PyObject*
Py_GetSnapshotAllocationRecords(
        const allocations_t& all_records,
        size_t record_index,
        bool merge_threads);

}  // namespace memray::api
