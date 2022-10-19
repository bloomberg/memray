#include <numeric>

#include "snapshot.h"

namespace memray::api {

bool
LocationKey::operator==(const LocationKey& rhs) const
{
    return python_frame_id == rhs.python_frame_id && native_frame_id == rhs.native_frame_id
           && thread_id == rhs.thread_id;
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
            const auto removed = d_mmap_intervals.removeInterval(address, size);

            if (!removed.has_value()) {
                break;
            }
            size_t removed_size = std::accumulate(
                    removed.value().begin(),
                    removed.value().cend(),
                    0,
                    [](size_t sum, const std::pair<Interval, Allocation>& range) {
                        return sum + range.first.size();
                    });
            d_current_memory -= removed_size;
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
