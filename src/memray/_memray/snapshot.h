#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
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

    struct RemovalStats
    {
        size_t total_freed_bytes;
        std::vector<std::pair<Interval, T>> freed_allocations;
        std::vector<std::pair<Interval, T>> shrunk_allocations;
        std::vector<std::pair<Interval, T>> split_allocations;
    };

    RemovalStats removeInterval(uintptr_t start, size_t size)
    {
        RemovalStats stats{};

        if (size <= 0) {
            return stats;
        }

        std::vector<std::pair<Interval, T>> new_intervals;
        new_intervals.reserve(d_intervals.size() + 1);  // We create at most 1 new interval.
        const auto removed_interval = Interval(start, start + size);

        for (auto& [interval, value] : d_intervals) {
            std::optional<Interval> maybe_intersection = interval.intersection(removed_interval);
            if (!maybe_intersection) {
                // Keep this interval entirely (the removed interval doesn't overlap it).
                new_intervals.emplace_back(interval, value);
                continue;
            }

            const auto& intersection = maybe_intersection.value();
            stats.total_freed_bytes += intersection.size();
            if (intersection == interval) {
                // Keep none of this interval (the removed interval contains it).
                stats.freed_allocations.emplace_back(intersection, value);
            } else if (intersection.leftIntersects(interval)) {
                // Keep the end of this interval (the removed interval overlaps the start).
                stats.shrunk_allocations.emplace_back(intersection, value);
                new_intervals.emplace_back(Interval{intersection.end, interval.end}, value);
            } else if (intersection.rightIntersects(interval)) {
                // Keep the start of this interval (the removed interval overlaps the end).
                stats.shrunk_allocations.emplace_back(intersection, value);
                new_intervals.emplace_back(Interval{interval.begin, intersection.begin}, value);
            } else {
                // Split this interval in two (the removed interval overlaps the middle).
                stats.split_allocations.emplace_back(intersection, value);
                new_intervals.emplace_back(Interval{interval.begin, intersection.begin}, value);
                new_intervals.emplace_back(Interval{intersection.end, interval.end}, value);
            }
        }

        d_intervals = new_intervals;
        return stats;
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

    const_iterator begin() const
    {
        return d_intervals.begin();
    }

    const_iterator end() const
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

class AggregatedCaptureReaggregator : public AbstractAggregator
{
  public:
    void addAllocation(const Allocation& allocation) override;
    reduced_snapshot_map_t getSnapshotAllocations(bool merge_threads) override;

  private:
    std::vector<Allocation> d_allocations;
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

// Like LocationKey, but considers the native_segment_generation and the
// allocator to be part of the key. Arguably it's a bug that LocationKey
// doesn't, for each of these. For now, I'm defining a separate type to avoid
// scope creep, but we should merge these.
struct HighWaterMarkLocationKey
{
    // Ordered widest field to narrowest, to avoid padding.
    thread_id_t thread_id;
    size_t python_frame_id;
    size_t native_frame_id;
    size_t native_segment_generation;
    hooks::Allocator allocator;

    bool operator==(const HighWaterMarkLocationKey& rhs) const;
    bool operator!=(const HighWaterMarkLocationKey& rhs) const;
    bool operator<(const HighWaterMarkLocationKey& rhs) const;
};

struct HighWaterMarkLocationKeyHash
{
    size_t operator()(const HighWaterMarkLocationKey& p) const
    {
        // Keep the fewest bits from the hashes of the fields that vary least.
        size_t ret = std::hash<hooks::Allocator>{}(p.allocator);
        ret = (ret << 1) ^ std::hash<size_t>{}(p.native_segment_generation);
        ret = (ret << 1) ^ std::hash<thread_id_t>{}(p.thread_id);
        ret = (ret << 1) ^ std::hash<size_t>{}(p.native_frame_id);
        ret = (ret << 1) ^ std::hash<size_t>{}(p.python_frame_id);
        return ret;
    }
};

struct Contribution
{
    size_t bytes;
    size_t allocations;
};

bool
operator==(const Contribution& lhs, const Contribution& rhs);

bool
operator!=(const Contribution& lhs, const Contribution& rhs);

struct HistoricalContribution
{
    size_t as_of_snapshot;
    size_t peak_index;
    Contribution contrib;
};

class UsageHistory
{
  public:
    void recordUsageDelta(
            const std::vector<size_t>& highest_peak_by_snapshot,
            size_t current_peak,
            size_t count_delta,
            size_t bytes_delta);

    Contribution highWaterMarkContribution(size_t highest_peak) const;
    Contribution leaksContribution() const;
    std::vector<HistoricalContribution> contributionsBySnapshot(
            const std::vector<size_t>& highest_peak_by_snapshot,
            size_t current_peak) const;

  private:
    // This class represents allocations observed at some location over time.
    // When an allocation or deallocation is observed, we first check if a new
    // peak was discovered after the last time an allocation or deallocation
    // was performed here. If so, the counters tracking what happened since the
    // last peak must be merged into allocations_contributed_to_last_known_peak
    // and bytes_contributed_to_last_known_peak and reset: they didn't
    // contribute to the previous peak, but they are accounted for in the newly
    // discovered peak. Finally, we update those counters to account for
    // allocations or deallocations since the current peak.
    struct UsageHistoryImpl
    {
        uint64_t last_known_snapshot;
        uint64_t last_known_peak;
        size_t allocations_contributed_to_last_known_peak;
        size_t bytes_contributed_to_last_known_peak;
        // NOTE: We may have more deallocations than allocations since the last
        // peak, or more bytes deallocated than allocated. These 2 size_t's
        // may represent negative counts as large positive numbers. That's OK:
        // they represent deltas since the last known peak, and are always
        // added to the values from the last known peak. Unsigned integers use
        // modular arithmetic, and addition will overflow to the correct value.
        size_t count_since_last_peak;
        size_t bytes_since_last_peak;

        // Update so that `last_known_peak == new_peak`.
        void rebase(size_t new_peak);
    };

    UsageHistoryImpl d_history{};
    std::vector<HistoricalContribution> d_heap_contribution_by_snapshot;

    // Append records for already-completed snapshots to the given vector.
    UsageHistoryImpl recordContributionsToCompletedSnapshots(
            const std::vector<size_t>& highest_peak_by_snapshot,
            std::vector<HistoricalContribution>& heap_contribution_by_snapshot) const;
};

struct AllocationLifetime
{
    size_t allocatedBeforeSnapshot;
    size_t deallocatedBeforeSnapshot;  // SIZE_MAX if never deallocated
    HighWaterMarkLocationKey key;
    size_t n_allocations;
    size_t n_bytes;
};

class HighWaterMarkAggregator
{
  public:
    using Index = std::vector<AllocationLifetime>;

    void addAllocation(const Allocation& allocation);
    void captureSnapshot();

    size_t getCurrentHeapSize() const noexcept;
    std::vector<size_t> highWaterMarkBytesBySnapshot() const;
    Index generateIndex() const;

    using allocation_callback_t = std::function<bool(const AggregatedAllocation&)>;
    bool visitAllocations(const allocation_callback_t& callback) const;

  private:
    // For each call to captureSnapshot(), record the index of the highest
    // high water mark found since the last snapshot was taken.
    std::vector<size_t> d_high_water_mark_index_by_snapshot;

    // For each call to captureSnapshot(), record the heap size at the highest
    // high water mark found since the last snapshot was taken.
    std::vector<size_t> d_high_water_mark_bytes_by_snapshot;

    // Number of high water marks found (incremented on the falling edge,
    // as well as on a new snapshot being taken).
    uint64_t d_peak_count{};
    size_t d_heap_size_at_last_peak{};
    size_t d_current_heap_size{};

    // Information about allocations and deallocations, aggregated by location.
    using UsageHistoryByLocation =
            std::unordered_map<HighWaterMarkLocationKey, UsageHistory, HighWaterMarkLocationKeyHash>;
    UsageHistoryByLocation d_usage_history_by_location;

    // Simple allocations contributing to the current heap size.
    std::unordered_map<uintptr_t, Allocation> d_ptr_to_allocation;

    // Ranged allocations contributing to the current heap size.
    IntervalTree<Allocation> d_mmap_intervals;

    UsageHistory& getUsageHistory(const Allocation& allocation);
    void recordUsageDelta(const Allocation& allocation, size_t count_delta, size_t bytes_delta);
    reduced_snapshot_map_t getAllocations(bool merge_threads, bool stop_at_high_water_mark) const;
};

class AllocationLifetimeAggregator
{
  public:
    void addAllocation(const Allocation& allocation);
    void captureSnapshot();

    std::vector<AllocationLifetime> generateIndex() const;

  private:
    size_t d_num_snapshots{};

    struct allocation_history_key_hash
    {
        size_t operator()(const std::tuple<size_t, size_t, HighWaterMarkLocationKey>& key) const
        {
            size_t ret = HighWaterMarkLocationKeyHash{}(std::get<2>(key));
            ret = (ret << 1) ^ std::get<1>(key);
            ret = (ret << 1) ^ std::get<0>(key);
            return ret;
        }
    };

    // Record of freed allocations that spanned multiple snapshots.
    std::unordered_map<
            std::tuple<size_t, size_t, HighWaterMarkLocationKey>,
            std::pair<size_t, size_t>,
            allocation_history_key_hash>
            d_allocation_history;

    // Simple allocations contributing to the current heap size.
    std::unordered_map<uintptr_t, std::pair<Allocation, size_t>> d_ptr_to_allocation;

    // Ranged allocations contributing to the current heap size.
    IntervalTree<std::pair<std::shared_ptr<Allocation>, size_t>> d_mmap_intervals;

    HighWaterMarkLocationKey extractKey(const Allocation& allocation) const;

    void recordRangedDeallocation(
            const std::shared_ptr<Allocation>& allocation,
            size_t bytes_deallocated,
            size_t generation_allocated);

    void recordDeallocation(
            const HighWaterMarkLocationKey& key,
            size_t count_delta,
            size_t bytes_delta,
            size_t generation);
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
