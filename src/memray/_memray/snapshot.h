#pragma once

#include <functional>
#include <optional>
#include <unordered_map>
#include <vector>

#include "Python.h"

#include "frame_tree.h"
#include "records.h"

namespace memray::api {

using namespace tracking_api;

const thread_id_t NO_THREAD_INFO = 0;

struct LocationKey
{
    size_t python_frame_id;
    size_t native_frame_id;
    thread_id_t thread_id;

    bool operator==(const LocationKey& rhs) const;
};

struct index_thread_pair_hash
{
    std::size_t operator()(const LocationKey& p) const
    {
        // Reduce the risk of the Python frame ID and native frame ID hashing
        // to the same value and cancelling each other out by adding a fixed
        // offset to one of them. Don't worry about collisions with the TID:
        // it's of a fundamentally different type and collisions are unlikely.
        return std::hash<size_t>{}(p.python_frame_id)
               xor std::hash<size_t>{}(p.native_frame_id + 2147483647)
               xor std::hash<thread_id_t>{}(p.thread_id);
    }
};

using allocations_t = std::vector<Allocation>;
using reduced_snapshot_map_t = std::unordered_map<LocationKey, Allocation, index_thread_pair_hash>;

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
            // This interval doesn't contain the element to removed_interval, so don't removed_interval
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

    size_t size()
    {
        size_t result = 0;
        std::for_each(d_intervals.begin(), d_intervals.end(), [&](const auto& pair) {
            result += pair.first.size();
        });
        return result;
    }

    iterator begin()
    {
        return d_intervals.begin();
    }

    iterator end()
    {
        return d_intervals.end();
    }

    const_iterator cbegin()
    {
        return d_intervals.cbegin();
    }

    const_iterator cend()
    {
        return d_intervals.cend();
    }
};

class SnapshotAllocationAggregator
{
  private:
    size_t d_index{0};
    IntervalTree<Allocation> d_interval_tree;
    std::unordered_map<uintptr_t, Allocation> d_ptr_to_allocation{};

  public:
    void addAllocation(const Allocation& allocation);
    reduced_snapshot_map_t getSnapshotAllocations(bool merge_threads);
};

PyObject*
Py_ListFromSnapshotAllocationRecords(const reduced_snapshot_map_t& stack_to_allocation);

struct HighWatermark
{
    size_t index{0};
    size_t peak_memory{0};
};

class HighWatermarkFinder
{
  public:
    HighWatermarkFinder() = default;
    void processAllocation(const Allocation& allocation);
    HighWatermark getHighWatermark() const noexcept;

  private:
    HighWatermarkFinder(const HighWatermarkFinder&) = delete;
    HighWatermarkFinder& operator=(const HighWatermarkFinder&) = delete;

    void updatePeak(size_t index) noexcept;

    HighWatermark d_last_high_water_mark;
    size_t d_current_memory{0};
    size_t d_allocations_seen{0};
    std::unordered_map<uintptr_t, size_t> d_ptr_to_allocation_size{};
    IntervalTree<Allocation> d_mmap_intervals;
};

PyObject*
Py_GetSnapshotAllocationRecords(
        const allocations_t& all_records,
        size_t record_index,
        bool merge_threads);

}  // namespace memray::api
