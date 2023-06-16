#include "snapshot.h"

#include <numeric>
#include <unordered_set>

namespace memray::api {

bool
LocationKey::operator==(const LocationKey& rhs) const
{
    return python_frame_id == rhs.python_frame_id && native_frame_id == rhs.native_frame_id
           && thread_id == rhs.thread_id;
}

bool
HighWaterMarkLocationKey::operator==(const HighWaterMarkLocationKey& rhs) const
{
    return thread_id == rhs.thread_id && python_frame_id == rhs.python_frame_id
           && native_frame_id == rhs.native_frame_id
           && native_segment_generation == rhs.native_segment_generation && allocator == rhs.allocator;
}

bool
HighWaterMarkLocationKey::operator!=(const HighWaterMarkLocationKey& rhs) const
{
    return !(*this == rhs);
}

bool
HighWaterMarkLocationKey::operator<(const HighWaterMarkLocationKey& rhs) const
{
    if (thread_id != rhs.thread_id) {
        return thread_id < rhs.thread_id;
    } else if (python_frame_id != rhs.python_frame_id) {
        return python_frame_id < rhs.python_frame_id;
    } else if (native_frame_id != rhs.native_frame_id) {
        return native_frame_id < rhs.native_frame_id;
    } else if (native_segment_generation != rhs.native_segment_generation) {
        return native_segment_generation < rhs.native_segment_generation;
    } else if (allocator != rhs.allocator) {
        return allocator < rhs.allocator;
    }
    return false;
}

bool
operator<(const AllocationLifetime& lhs, const AllocationLifetime& rhs)
{
    // Sort first by location, then allocatedBefore, then deallocatedBefore.
    // Sort by n_bytes if allocatedBefore/deallocatedBefore are equal,
    // so that our test suite gets records in a predictable order.
    if (lhs.key != rhs.key) {
        return lhs.key < rhs.key;
    } else if (lhs.allocatedBeforeSnapshot != rhs.allocatedBeforeSnapshot) {
        return lhs.allocatedBeforeSnapshot < rhs.allocatedBeforeSnapshot;
    } else if (lhs.deallocatedBeforeSnapshot != rhs.deallocatedBeforeSnapshot) {
        return lhs.deallocatedBeforeSnapshot < rhs.deallocatedBeforeSnapshot;
    } else {
        return lhs.n_bytes < rhs.n_bytes;
    }
}

Interval::Interval(uintptr_t begin, uintptr_t end)
: begin(begin)
, end(end)
{
}

std::optional<Interval>
Interval::intersection(const Interval& other) const
{
    auto max_start = std::max(begin, other.begin);
    auto min_end = std::min(end, other.end);
    if (min_end <= max_start) {
        return std::nullopt;
    } else {
        return Interval(max_start, min_end);
    }
}

size_t
Interval::size() const
{
    return end - begin;
}

bool
Interval::operator==(const Interval& rhs) const
{
    return begin == rhs.begin && end == rhs.end;
}

bool
Interval::operator!=(const Interval& rhs) const
{
    return !(rhs == *this);
}

bool
Interval::leftIntersects(const Interval& other) const
{
    return (begin == other.begin) && (end < other.end);
}

bool
Interval::rightIntersects(const Interval& other) const
{
    return (begin > other.begin) && (end == other.end);
}

void
SnapshotAllocationAggregator::addAllocation(const Allocation& allocation)
{
    switch (hooks::allocatorKind(allocation.allocator)) {
        case hooks::AllocatorKind::SIMPLE_ALLOCATOR: {
            d_ptr_to_allocation[allocation.address] = allocation;
            break;
        }
        case hooks::AllocatorKind::SIMPLE_DEALLOCATOR: {
            auto it = d_ptr_to_allocation.find(allocation.address);
            if (it != d_ptr_to_allocation.end()) {
                d_ptr_to_allocation.erase(it);
            }
            break;
        }
        case hooks::AllocatorKind::RANGED_ALLOCATOR: {
            d_interval_tree.addInterval(allocation.address, allocation.size, allocation);
            break;
        }
        case hooks::AllocatorKind::RANGED_DEALLOCATOR: {
            d_interval_tree.removeInterval(allocation.address, allocation.size);
            break;
        }
    }
    d_index++;
}

reduced_snapshot_map_t
SnapshotAllocationAggregator::getSnapshotAllocations(bool merge_threads)
{
    reduced_snapshot_map_t stack_to_allocation{};

    for (const auto& it : d_ptr_to_allocation) {
        const Allocation& record = it.second;
        const thread_id_t thread_id = merge_threads ? NO_THREAD_INFO : record.tid;
        auto loc_key = LocationKey{record.frame_index, record.native_frame_id, thread_id};
        auto alloc_it = stack_to_allocation.find(loc_key);
        if (alloc_it == stack_to_allocation.end()) {
            stack_to_allocation.insert(alloc_it, std::pair(loc_key, record));
        } else {
            alloc_it->second.size += record.size;
            alloc_it->second.n_allocations += 1;
        }
    }

    // Process ranged allocations. As there can be partial deallocations in mmap'd regions,
    // we update the allocation to reflect the actual size at the peak, based on the lengths
    // of the ranges in the interval tree.
    for (const auto& [range, allocation] : d_interval_tree) {
        const thread_id_t thread_id = merge_threads ? NO_THREAD_INFO : allocation.tid;
        auto loc_key = LocationKey{allocation.frame_index, allocation.native_frame_id, thread_id};
        auto alloc_it = stack_to_allocation.find(loc_key);
        if (alloc_it == stack_to_allocation.end()) {
            Allocation new_alloc = allocation;
            new_alloc.size = range.size();
            stack_to_allocation.insert(alloc_it, std::pair(loc_key, new_alloc));
        } else {
            alloc_it->second.size += range.size();
            alloc_it->second.n_allocations += 1;
        }
    }

    return stack_to_allocation;
}

TemporaryAllocationsAggregator::TemporaryAllocationsAggregator(size_t max_items)
: d_max_items(max_items)
{
}

void
TemporaryAllocationsAggregator::addAllocation(const Allocation& allocation)
{
    hooks::AllocatorKind kind = hooks::allocatorKind(allocation.allocator);
    auto it = d_current_allocations.find(allocation.tid);
    switch (kind) {
        case hooks::AllocatorKind::SIMPLE_ALLOCATOR:
        case hooks::AllocatorKind::RANGED_ALLOCATOR: {
            if (it == d_current_allocations.end()) {
                it = d_current_allocations.insert(
                        it,
                        std::pair(allocation.tid, std::deque<Allocation>()));
            }

            it->second.emplace_front(allocation);
            if (it->second.size() > d_max_items) {
                it->second.pop_back();
            }
            break;
        }
        case hooks::AllocatorKind::SIMPLE_DEALLOCATOR:
        case hooks::AllocatorKind::RANGED_DEALLOCATOR: {
            if (it == d_current_allocations.end()) {
                break;
            }

            auto alloc_it =
                    std::find_if(it->second.begin(), it->second.end(), [&](auto& current_allocation) {
                        bool match = (current_allocation.address == allocation.address);
                        if (kind == hooks::AllocatorKind::RANGED_DEALLOCATOR) {
                            match = match && (current_allocation.size == allocation.size);
                        }
                        return match;
                    });

            if (alloc_it != it->second.end()) {
                d_temporary_allocations.push_back(*alloc_it);
            }
            break;
        }
    }
}

reduced_snapshot_map_t
TemporaryAllocationsAggregator::getSnapshotAllocations(bool merge_threads)
{
    reduced_snapshot_map_t stack_to_allocation{};

    for (const auto& record : d_temporary_allocations) {
        const thread_id_t thread_id = merge_threads ? NO_THREAD_INFO : record.tid;
        auto loc_key = LocationKey{record.frame_index, record.native_frame_id, thread_id};
        auto alloc_it = stack_to_allocation.find(loc_key);
        if (alloc_it == stack_to_allocation.end()) {
            stack_to_allocation.insert(alloc_it, std::pair(loc_key, record));
        } else {
            alloc_it->second.size += record.size;
            alloc_it->second.n_allocations += 1;
        }
    }

    return stack_to_allocation;
}

void
AggregatedCaptureReaggregator::addAllocation(const Allocation& allocation)
{
    // Store a list of pre-aggregated leaked or high water mark allocations.
    assert(!hooks::isDeallocator(allocation.allocator));
    assert(0 == allocation.address);

    if (allocation.n_allocations != 0) {
        d_allocations.push_back(allocation);
    }
}

reduced_snapshot_map_t
AggregatedCaptureReaggregator::getSnapshotAllocations(bool merge_threads)
{
    // Spit them back out, possibly with threads merged.
    reduced_snapshot_map_t stack_to_allocation{};

    for (const auto& record : d_allocations) {
        const thread_id_t thread_id = merge_threads ? NO_THREAD_INFO : record.tid;
        auto loc_key = LocationKey{record.frame_index, record.native_frame_id, thread_id};
        auto alloc_it = stack_to_allocation.find(loc_key);
        if (alloc_it == stack_to_allocation.end()) {
            stack_to_allocation.insert(alloc_it, std::pair(loc_key, record));
        } else {
            alloc_it->second.size += record.size;
            alloc_it->second.n_allocations += 1;
        }
    }

    return stack_to_allocation;
}

bool
operator==(const Contribution& lhs, const Contribution& rhs)
{
    return lhs.allocations == rhs.allocations && lhs.bytes == rhs.bytes;
}

bool
operator!=(const Contribution& lhs, const Contribution& rhs)
{
    return !(lhs == rhs);
}

UsageHistory&
HighWaterMarkAggregator::getUsageHistory(const Allocation& allocation)
{
    HighWaterMarkLocationKey loc_key{
            allocation.tid,
            allocation.frame_index,
            allocation.native_frame_id,
            allocation.native_segment_generation,
            allocation.allocator};

    auto it = d_usage_history_by_location.find(loc_key);
    if (it == d_usage_history_by_location.end()) {
        assert(!hooks::isDeallocator(allocation.allocator));
        it = d_usage_history_by_location.emplace(loc_key, UsageHistory{}).first;
    }
    return it->second;
}

void
UsageHistory::UsageHistoryImpl::rebase(size_t new_peak)
{
    if (last_known_peak != new_peak) {
        assert(last_known_peak < new_peak);  // we can only move forward.
        // Any deltas since the last peak are part of the new one.
        allocations_contributed_to_last_known_peak += count_since_last_peak;
        bytes_contributed_to_last_known_peak += bytes_since_last_peak;

        count_since_last_peak = 0;
        bytes_since_last_peak = 0;

        last_known_peak = new_peak;
    }
}

UsageHistory::UsageHistoryImpl
UsageHistory::recordContributionsToCompletedSnapshots(
        const std::vector<size_t>& highest_peak_by_snapshot,
        std::vector<HistoricalContribution>& heap_contribution_by_snapshot) const
{
    size_t current_snapshot = highest_peak_by_snapshot.size();
    auto history = d_history;

    // If any snapshots have completed since this location's last allocation
    // or deallocation, we need to record the final amount we contributed to
    // their HWMs in `heap_contribution_by_snapshot`. This loop will fire:
    // - 0 times if no snapshots are newly completed.
    // - 1 time if only 1 snapshot is newly completed.
    // - 1 time if more than 1 snapshot is newly completed but we contributed
    //   the same amount to the HWM of each of them.
    // - 2 times if at least 2 snapshots are newly completed and we contributed
    //   different amounts to the HWM of the first than the rest. This means we
    //   had (de)allocations during the first snapshot but after its HWM, which
    //   we need to record as contributions to the HWM of the rest.
    while (history.last_known_snapshot != current_snapshot) {
        assert(history.last_known_snapshot < current_snapshot);
        size_t last_snapshot_peak = highest_peak_by_snapshot.at(history.last_known_snapshot);
        history.rebase(last_snapshot_peak);

        HistoricalContribution hc{
                history.last_known_snapshot,
                last_snapshot_peak,
                {history.bytes_contributed_to_last_known_peak,
                 history.allocations_contributed_to_last_known_peak}};

        bool changed;
        if (!heap_contribution_by_snapshot.empty()) {
            // See if the amount contributed has changed since the last record.
            changed = heap_contribution_by_snapshot.back().contrib != hc.contrib;
        } else {
            // An empty vector implicitly no contributed bytes/allocations.
            changed = Contribution{0, 0} != hc.contrib;
        }

        if (changed) {
            // Only record amounts that differ from the last recorded amount.
            // We represent "runs" of the same value implicitly.
            heap_contribution_by_snapshot.push_back(hc);
        }

        if (history.count_since_last_peak) {
            history.last_known_snapshot++;
        } else {
            history.last_known_snapshot = current_snapshot;
        }
    }
    return history;
}

void
UsageHistory::recordUsageDelta(
        const std::vector<size_t>& highest_peak_by_snapshot,
        size_t current_peak,
        size_t count_delta,
        size_t bytes_delta)
{
    size_t current_snapshot = highest_peak_by_snapshot.size();
    if (d_history.last_known_snapshot < current_snapshot) {
        d_history = recordContributionsToCompletedSnapshots(
                highest_peak_by_snapshot,
                d_heap_contribution_by_snapshot);
    }

    if (d_history.last_known_peak != current_peak) {
        d_history.rebase(current_peak);
    }

    d_history.count_since_last_peak += count_delta;
    d_history.bytes_since_last_peak += bytes_delta;
}

Contribution
UsageHistory::highWaterMarkContribution(size_t highest_peak) const
{
    // If the highest peak was in a snapshot we've already moved past, return
    // our last contribution to a peak <= highest_peak, or an empty
    // contribution if no allocations occurred here before that highest peak.
    if (highest_peak < d_history.last_known_peak) {
        auto it = std::lower_bound(
                d_heap_contribution_by_snapshot.rbegin(),
                d_heap_contribution_by_snapshot.rend(),
                highest_peak,
                [](const HistoricalContribution& hc, size_t highest_peak) {
                    return hc.peak_index > highest_peak;
                });
        if (it == d_heap_contribution_by_snapshot.rend()) {
            return {0, 0};
        }
        return it->contrib;
    }

    auto total = d_history;
    total.rebase(highest_peak);
    Contribution ret;
    ret.bytes = total.bytes_contributed_to_last_known_peak;
    ret.allocations = total.allocations_contributed_to_last_known_peak;
    return ret;
}

Contribution
UsageHistory::leaksContribution() const
{
    Contribution ret;
    ret.bytes = d_history.bytes_contributed_to_last_known_peak + d_history.bytes_since_last_peak;
    ret.allocations =
            d_history.allocations_contributed_to_last_known_peak + d_history.count_since_last_peak;
    return ret;
}

std::vector<HistoricalContribution>
UsageHistory::contributionsBySnapshot(
        const std::vector<size_t>& highest_peak_by_snapshot,
        size_t current_peak) const
{
    size_t current_snapshot = highest_peak_by_snapshot.size();
    auto ret = d_heap_contribution_by_snapshot;

    auto final = d_history;
    if (final.last_known_snapshot < current_snapshot) {
        final = recordContributionsToCompletedSnapshots(highest_peak_by_snapshot, ret);
    }

    if (final.last_known_peak != current_peak) {
        final.rebase(current_peak);
    }
    final.last_known_snapshot = current_snapshot;

    Contribution hwm{
            final.bytes_contributed_to_last_known_peak,
            final.allocations_contributed_to_last_known_peak};

    Contribution leaks = hwm;
    leaks.allocations += final.count_since_last_peak;
    leaks.bytes += final.bytes_since_last_peak;

    if (ret.empty() || ret.back().contrib != hwm) {
        ret.emplace_back(HistoricalContribution{final.last_known_snapshot, current_peak, hwm});
    }

    if (ret.empty() || ret.back().contrib != leaks) {
        ret.emplace_back(
                HistoricalContribution{final.last_known_snapshot + 1, static_cast<size_t>(-1), leaks});
    }

    return ret;
}

void
HighWaterMarkAggregator::recordUsageDelta(
        const Allocation& allocation,
        size_t count_delta,
        size_t bytes_delta)
{
    size_t new_heap_size = d_current_heap_size + bytes_delta;
    if (d_current_heap_size >= d_heap_size_at_last_peak && new_heap_size < d_current_heap_size) {
        // This is the falling edge of a peak we haven't yet recorded.
        d_peak_count += 1;
        d_heap_size_at_last_peak = d_current_heap_size;
    }
    d_current_heap_size = new_heap_size;

    auto& history = getUsageHistory(allocation);
    history.recordUsageDelta(
            d_high_water_mark_index_by_snapshot,
            d_peak_count,
            count_delta,
            bytes_delta);
}

void
HighWaterMarkAggregator::addAllocation(const Allocation& allocation_or_deallocation)
{
    // Note: Deallocation records don't tell us where the memory was allocated,
    //       so we need to save the records for allocations and cross-reference
    //       deallocations against them.
    switch (hooks::allocatorKind(allocation_or_deallocation.allocator)) {
        case hooks::AllocatorKind::SIMPLE_ALLOCATOR: {
            const Allocation& allocation = allocation_or_deallocation;
            recordUsageDelta(allocation, 1, allocation.size);
            d_ptr_to_allocation[allocation.address] = allocation;
            break;
        }
        case hooks::AllocatorKind::SIMPLE_DEALLOCATOR: {
            const Allocation& deallocation = allocation_or_deallocation;
            auto it = d_ptr_to_allocation.find(deallocation.address);
            if (it != d_ptr_to_allocation.end()) {
                const Allocation& allocation = it->second;
                recordUsageDelta(allocation, -1, -allocation.size);
                d_ptr_to_allocation.erase(it);
            }
            break;
        }
        case hooks::AllocatorKind::RANGED_ALLOCATOR: {
            const Allocation& allocation = allocation_or_deallocation;
            recordUsageDelta(allocation, 1, allocation.size);
            d_mmap_intervals.addInterval(allocation.address, allocation.size, allocation);
            break;
        }
        case hooks::AllocatorKind::RANGED_DEALLOCATOR: {
            const Allocation& deallocation = allocation_or_deallocation;
            auto removal_stats =
                    d_mmap_intervals.removeInterval(deallocation.address, deallocation.size);
            for (const auto& [interval, allocation] : removal_stats.freed_allocations) {
                recordUsageDelta(allocation, -1, -interval.size());
            }
            for (const auto& [interval, allocation] : removal_stats.shrunk_allocations) {
                recordUsageDelta(allocation, 0, -interval.size());
            }
            for (const auto& [interval, allocation] : removal_stats.split_allocations) {
                recordUsageDelta(allocation, 1, -interval.size());
            }
            break;
        }
    }
}

void
HighWaterMarkAggregator::captureSnapshot()
{
    if (d_current_heap_size >= d_heap_size_at_last_peak) {
        // We're currently on the rising edge of a new peak.
        d_high_water_mark_index_by_snapshot.push_back(d_peak_count + 1);
        d_high_water_mark_bytes_by_snapshot.push_back(d_current_heap_size);
    } else {
        d_high_water_mark_index_by_snapshot.push_back(d_peak_count);
        d_high_water_mark_bytes_by_snapshot.push_back(d_heap_size_at_last_peak);
    }

    // Count the start of a snapshot as a "peak", even though heap utilization
    // may in fact be lower than at a previous peak.
    d_peak_count++;
    d_heap_size_at_last_peak = d_current_heap_size;
}

size_t
HighWaterMarkAggregator::getCurrentHeapSize() const noexcept
{
    return d_current_heap_size;
}

std::vector<size_t>
HighWaterMarkAggregator::highWaterMarkBytesBySnapshot() const
{
    auto ret = d_high_water_mark_bytes_by_snapshot;
    ret.push_back(d_heap_size_at_last_peak);
    return ret;
}

HighWaterMarkAggregator::Index
HighWaterMarkAggregator::generateIndex() const
{
    std::vector<AllocationLifetime> index;

    uint64_t final_peak_count = d_peak_count;
    if (d_current_heap_size >= d_heap_size_at_last_peak) {
        // We're currently at a new peak that we haven't yet fallen from.
        final_peak_count++;
    }

    for (const auto& [location, history] : d_usage_history_by_location) {
        auto contribs =
                history.contributionsBySnapshot(d_high_water_mark_index_by_snapshot, final_peak_count);

        // Loop over all but the last historical contribution.
        for (size_t i = 0; i + 1 < contribs.size(); ++i) {
            auto& curr = contribs[i];
            auto& next = contribs[i + 1];

            index.emplace_back(AllocationLifetime{
                    curr.as_of_snapshot,
                    next.as_of_snapshot,
                    location,
                    curr.contrib.allocations,
                    curr.contrib.bytes});
        }

        if (!contribs.empty()) {
            // The last one is special because there's no end snapshot.
            auto& curr = contribs.back();

            index.emplace_back(AllocationLifetime{
                    curr.as_of_snapshot,
                    static_cast<size_t>(-1),
                    location,
                    curr.contrib.allocations,
                    curr.contrib.bytes});
        }
    }

    // Finally, sort the vector we're returning, so that our callers can count
    // on all intervals for a given location being contiguous.
    std::sort(index.begin(), index.end());
    return index;
}

bool
HighWaterMarkAggregator::visitAllocations(const allocation_callback_t& callback) const
{
    // Find true peak: max(highest snapshot peak, latest peak, current usage)
    uint64_t final_peak_count = 0;
    uint64_t final_peak_bytes = 0;
    for (size_t i = 0; i < d_high_water_mark_index_by_snapshot.size(); ++i) {
        if (d_high_water_mark_bytes_by_snapshot[i] > final_peak_bytes) {
            final_peak_bytes = d_high_water_mark_bytes_by_snapshot[i];
            final_peak_count = d_high_water_mark_index_by_snapshot[i];
        }
    }

    if (d_heap_size_at_last_peak > final_peak_bytes) {
        final_peak_count = d_peak_count;
        final_peak_bytes = d_heap_size_at_last_peak;
    }

    if (d_current_heap_size >= final_peak_bytes) {
        // We're currently at a new peak that we haven't yet fallen from.
        final_peak_count = d_peak_count + 1;
        final_peak_bytes = d_current_heap_size;
    }

    return std::all_of(
            d_usage_history_by_location.begin(),
            d_usage_history_by_location.end(),
            [&](const auto& entry) {
                const auto& [loc, usage] = entry;
                Contribution hwm = usage.highWaterMarkContribution(final_peak_count);
                Contribution leaks = usage.leaksContribution();
                AggregatedAllocation alloc{
                        loc.thread_id,
                        loc.allocator,
                        loc.native_frame_id,
                        loc.python_frame_id,
                        loc.native_segment_generation,
                        hwm.allocations,
                        leaks.allocations,
                        hwm.bytes,
                        leaks.bytes};

                return callback(alloc);
            });
}

void
AllocationLifetimeAggregator::addAllocation(const Allocation& allocation_or_deallocation)
{
    // Note: Deallocation records don't tell us where the memory was allocated,
    //       so we need to save the records for allocations and cross-reference
    //       deallocations against them.
    switch (hooks::allocatorKind(allocation_or_deallocation.allocator)) {
        case hooks::AllocatorKind::SIMPLE_ALLOCATOR: {
            const Allocation& allocation = allocation_or_deallocation;
            size_t generation = d_num_snapshots;
            d_ptr_to_allocation[allocation.address] = {allocation, generation};
            break;
        }
        case hooks::AllocatorKind::SIMPLE_DEALLOCATOR: {
            const Allocation& deallocation = allocation_or_deallocation;
            const auto it = d_ptr_to_allocation.find(deallocation.address);
            if (it != d_ptr_to_allocation.end()) {
                const auto& [allocation, generation] = it->second;
                recordDeallocation(extractKey(allocation), 1, allocation.size, generation);
                d_ptr_to_allocation.erase(it);
            }
            break;
        }
        case hooks::AllocatorKind::RANGED_ALLOCATOR: {
            const Allocation& allocation = allocation_or_deallocation;
            size_t generation = d_num_snapshots;
            d_mmap_intervals.addInterval(
                    allocation.address,
                    allocation.size,
                    {std::make_shared<Allocation>(allocation), generation});
            break;
        }
        case hooks::AllocatorKind::RANGED_DEALLOCATOR: {
            const Allocation& deallocation = allocation_or_deallocation;
            auto removal_stats =
                    d_mmap_intervals.removeInterval(deallocation.address, deallocation.size);
            for (const auto& [interval, pair] : removal_stats.freed_allocations) {
                recordRangedDeallocation(pair.first, interval.size(), pair.second);
            }
            for (const auto& [interval, pair] : removal_stats.shrunk_allocations) {
                recordRangedDeallocation(pair.first, interval.size(), pair.second);
            }
            for (const auto& [interval, pair] : removal_stats.split_allocations) {
                recordRangedDeallocation(pair.first, interval.size(), pair.second);
            }
            break;
        }
    }
}

HighWaterMarkLocationKey
AllocationLifetimeAggregator::extractKey(const Allocation& allocation) const
{
    return {allocation.tid,
            allocation.frame_index,
            allocation.native_frame_id,
            allocation.native_segment_generation,
            allocation.allocator};
}

void
AllocationLifetimeAggregator::recordRangedDeallocation(
        const std::shared_ptr<Allocation>& allocation_ptr,
        size_t bytes_deallocated,
        size_t generation_allocated)
{
    // We hold one reference, and the IntervalTree may or may not hold others.
    // We use a count of 0 for all but the last deallocation of a range so that
    // partial deallocations won't affect the count of allocations by location.
    bool fully_deallocated = allocation_ptr.use_count() == 1;
    recordDeallocation(
            extractKey(*allocation_ptr),
            (fully_deallocated ? 1 : 0),
            bytes_deallocated,
            generation_allocated);
}

void
AllocationLifetimeAggregator::recordDeallocation(
        const HighWaterMarkLocationKey& key,
        size_t count_delta,
        size_t bytes_delta,
        size_t generation)
{
    if (d_num_snapshots == generation) {
        // Allocated and deallocated within the same snapshot. We can ignore this.
        return;
    }

    auto& counts = d_allocation_history[std::make_tuple(generation, d_num_snapshots, key)];
    counts.first += count_delta;
    counts.second += bytes_delta;
}

void
AllocationLifetimeAggregator::captureSnapshot()
{
    ++d_num_snapshots;
}

std::vector<AllocationLifetime>
AllocationLifetimeAggregator::generateIndex() const
{
    struct KeyHash
    {
        size_t operator()(const std::pair<size_t, HighWaterMarkLocationKey>& key) const
        {
            size_t ret = HighWaterMarkLocationKeyHash{}(std::get<1>(key));
            ret = (ret << 1) ^ std::get<0>(key);
            return ret;
        }
    };

    // First, gather information about allocations that were never deallocated.
    // These are still sitting in `d_ptr_to_allocation` and `d_mmap_intervals`,
    // since `d_allocation_history` only gets updated when things are freed.
    // We can't update `d_allocation_history` here since this method is const.
    std::unordered_map<std::pair<size_t, HighWaterMarkLocationKey>, std::pair<size_t, size_t>, KeyHash>
            leaks;

    for (const auto& [ptr, allocation_and_generation] : d_ptr_to_allocation) {
        (void)ptr;
        const auto& [allocation, generation] = allocation_and_generation;
        auto& counts = leaks[std::make_pair(generation, extractKey(allocation))];
        counts.first += 1;
        counts.second += allocation.size;
    }

    std::unordered_set<void*> leaked_mappings;
    for (const auto& [interval, allocation_ptr_and_generation] : d_mmap_intervals) {
        const auto& [allocation_ptr, generation] = allocation_ptr_and_generation;
        auto& counts = leaks[std::make_pair(generation, extractKey(*allocation_ptr))];

        // Ensure we only count each allocation once, even if it's been split.
        auto inserted = leaked_mappings.insert(allocation_ptr.get()).second;
        counts.first += (inserted ? 1 : 0);
        counts.second += interval.size();
    }

    // Then, combine information about both leaked allocations and freed
    // allocations into the vector we'll be returning.
    std::vector<AllocationLifetime> ret;

    for (const auto& [when_where, how_much] : leaks) {
        const auto& [allocated_before, key] = when_where;
        const auto& [n_allocations, n_bytes] = how_much;
        ret.push_back({allocated_before, static_cast<size_t>(-1), key, n_allocations, n_bytes});
    }

    for (const auto& [when_where, how_much] : d_allocation_history) {
        const auto& [allocated_before, deallocated_before, key] = when_where;
        const auto& [n_allocations, n_bytes] = how_much;
        ret.push_back({allocated_before, deallocated_before, key, n_allocations, n_bytes});
    }

    // Finally, sort the vector we're returning, so that our callers can count
    // on all intervals for a given location being contiguous.
    std::sort(ret.begin(), ret.end());
    return ret;
}

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
reduceSnapshotAllocations(const allocations_t& records, size_t snapshot_index, bool merge_threads)
{
    assert(snapshot_index < records.size());

    SnapshotAllocationAggregator aggregator;

    std::for_each(records.cbegin(), records.cbegin() + snapshot_index + 1, [&](auto& record) {
        aggregator.addAllocation(record);
    });

    return aggregator.getSnapshotAllocations(merge_threads);
}

void
HighWatermarkFinder::updatePeak(size_t index) noexcept
{
    if (d_current_memory >= d_last_high_water_mark.peak_memory) {
        d_last_high_water_mark.index = index;
        d_last_high_water_mark.peak_memory = d_current_memory;
    }
}

void
HighWatermarkFinder::processAllocation(const Allocation& allocation)
{
    size_t index = d_allocations_seen++;
    switch (hooks::allocatorKind(allocation.allocator)) {
        case hooks::AllocatorKind::SIMPLE_ALLOCATOR: {
            d_current_memory += allocation.size;
            updatePeak(index);
            d_ptr_to_allocation_size[allocation.address] = allocation.size;
            break;
        }
        case hooks::AllocatorKind::SIMPLE_DEALLOCATOR: {
            auto it = d_ptr_to_allocation_size.find(allocation.address);
            if (it != d_ptr_to_allocation_size.end()) {
                d_current_memory -= it->second;
                d_ptr_to_allocation_size.erase(it);
            }
            updatePeak(index);
            break;
        }
        case hooks::AllocatorKind::RANGED_ALLOCATOR: {
            d_mmap_intervals.addInterval(allocation.address, allocation.size, allocation);
            d_current_memory += allocation.size;
            updatePeak(index);
            break;
        }
        case hooks::AllocatorKind::RANGED_DEALLOCATOR: {
            const auto address = allocation.address;
            const auto size = allocation.size;
            const auto removal_stats = d_mmap_intervals.removeInterval(address, size);
            d_current_memory -= removal_stats.total_freed_bytes;
            updatePeak(index);
            break;
        }
    }
}

HighWatermark
HighWatermarkFinder::getHighWatermark() const noexcept
{
    return d_last_high_water_mark;
}

size_t
HighWatermarkFinder::getCurrentWatermark() const noexcept
{
    return d_current_memory;
}

void
AllocationStatsAggregator::addAllocation(
        const Allocation& allocation,
        std::optional<frame_id_t> python_frame_id)
{
    d_high_water_mark_finder.processAllocation(allocation);
    if (hooks::isDeallocator(allocation.allocator)) {
        return;
    }
    d_total_allocations += 1;
    d_total_bytes_allocated += allocation.size;
    d_allocation_count_by_size[allocation.size] += 1;
    d_allocation_count_by_allocator[static_cast<int>(allocation.allocator)] += 1;
    auto& size_and_count = d_size_and_count_by_location[python_frame_id];
    size_and_count.first += allocation.size;
    size_and_count.second += 1;
}

PyObject*
Py_ListFromSnapshotAllocationRecords(const reduced_snapshot_map_t& stack_to_allocation)
{
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
Py_GetSnapshotAllocationRecords(
        const allocations_t& all_records,
        size_t record_index,
        bool merge_threads)
{
    if (all_records.empty()) {
        return PyList_New(0);
    }
    const auto stack_to_allocation = reduceSnapshotAllocations(all_records, record_index, merge_threads);
    return Py_ListFromSnapshotAllocationRecords(stack_to_allocation);
}

}  // namespace memray::api
