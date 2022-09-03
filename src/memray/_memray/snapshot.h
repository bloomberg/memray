#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <deque>
#include <functional>
#include <optional>
#include <unordered_map>
#include <vector>

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

class AbstractAggregator
{
  public:
    virtual void addAllocation(const Allocation& allocation) = 0;
    virtual reduced_snapshot_map_t getSnapshotAllocations(bool merge_threads) = 0;
    virtual ~AbstractAggregator() = default;
};

class SnapshotAllocationAggregator : public AbstractAggregator
{
  private:
    size_t d_index{0};
    IntervalTree<Allocation> d_interval_tree;
    std::unordered_map<uintptr_t, Allocation> d_ptr_to_allocation{};

  public:
    void addAllocation(const Allocation& allocation) override;
    reduced_snapshot_map_t getSnapshotAllocations(bool merge_threads) override;
};

class TemporaryAllocationsAggregator : public AbstractAggregator
{
  private:
    size_t d_max_items;
    std::unordered_map<thread_id_t, std::deque<Allocation>> d_current_allocations{};
    std::vector<Allocation> d_temporary_allocations{};

  public:
    TemporaryAllocationsAggregator(size_t max_items);
    void addAllocation(const Allocation& allocation) override;
    reduced_snapshot_map_t getSnapshotAllocations(bool merge_threads) override;
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
    size_t getCurrentWatermark() const noexcept;

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

class AllocationStatsAggregator
{
  public:
    void addAllocation(const Allocation& allocation, std::optional<frame_id_t> python_frame_id);

    uint64_t totalAllocations()
    {
        return d_total_allocations;
    }

    uint64_t totalBytesAllocated()
    {
        return d_total_bytes_allocated;
    }

    uint64_t peakBytesAllocated()
    {
        return d_high_water_mark_finder.getHighWatermark().peak_memory;
    }

    const std::unordered_map<size_t, uint64_t>& allocationCountBySize()
    {
        return d_allocation_count_by_size;
    }

    const std::unordered_map<int, uint64_t>& allocationCountByAllocator()
    {
        return d_allocation_count_by_allocator;
    }

    std::vector<std::pair<uint64_t, std::optional<frame_id_t>>> topLocationsBySize(size_t num_largest)
    {
        return topLocationsBySizeAndCountField<0>(num_largest);
    }

    std::vector<std::pair<uint64_t, std::optional<frame_id_t>>> topLocationsByCount(int num_largest)
    {
        return topLocationsBySizeAndCountField<1>(num_largest);
    }

  private:
    typedef std::pair<uint64_t, uint64_t> SizeAndCount;
    typedef std::unordered_map<std::optional<frame_id_t>, SizeAndCount> SizeAndCountByLocation;

    SizeAndCountByLocation d_size_and_count_by_location;
    std::unordered_map<size_t, uint64_t> d_allocation_count_by_size;
    std::unordered_map<int, uint64_t> d_allocation_count_by_allocator;
    HighWatermarkFinder d_high_water_mark_finder;
    uint64_t d_total_allocations{};
    uint64_t d_total_bytes_allocated{};

    template<int field>
    std::vector<
            std::pair<typename std::tuple_element<field, SizeAndCount>::type, std::optional<frame_id_t>>>
    topLocationsBySizeAndCountField(size_t num_largest)
    {
        if (num_largest == 0) {
            return {};
        }
        if (num_largest > d_size_and_count_by_location.size()) {
            num_largest = d_size_and_count_by_location.size();
        }

        std::vector<std::pair<uint64_t, std::optional<frame_id_t>>> heap;
        heap.reserve(d_size_and_count_by_location.size());
        for (auto it : d_size_and_count_by_location) {
            auto location = it.first;
            auto val = std::get<field>(it.second);
            heap.push_back({val, location});
        }
        std::make_heap(heap.begin(), heap.end());
        for (size_t i = 0; i < num_largest; ++i) {
            std::pop_heap(heap.begin(), heap.end() - i);
        }
        return {heap.rbegin(), heap.rbegin() + num_largest};
    }
};

PyObject*
Py_GetSnapshotAllocationRecords(
        const allocations_t& all_records,
        size_t record_index,
        bool merge_threads);

}  // namespace memray::api
