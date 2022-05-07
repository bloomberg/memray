#include <numeric>

#include "snapshot.h"

namespace memray::api {

namespace {  // unnamed

reduced_snapshot_map_t
reduceSnapshotAllocations(
        bool merge_threads,
        const IntervalTree<Allocation>& ranges,
        const std::unordered_map<uintptr_t, Allocation>& allocations_by_ptr)
{
    reduced_snapshot_map_t stack_to_allocation{};

    for (const auto& it : allocations_by_ptr) {
        const Allocation& record = it.second;
        const thread_id_t thread_id = merge_threads ? NO_THREAD_INFO : record.tid;
        auto alloc_it = stack_to_allocation.find(std::pair(record.frame_index, thread_id));
        if (alloc_it == stack_to_allocation.end()) {
            stack_to_allocation.insert(
                    alloc_it,
                    std::pair(std::pair(record.frame_index, thread_id), record));
        } else {
            alloc_it->second.size += record.size;
            alloc_it->second.n_allocations += 1;
        }
    }

    // Process ranged allocations. As there can be partial deallocations in mmap'd regions,
    // we update the allocation to reflect the actual size at the peak, based on the lengths
    // of the ranges in the interval tree.
    for (const auto& [range, allocation] : ranges) {
        const thread_id_t thread_id = merge_threads ? NO_THREAD_INFO : allocation.tid;
        auto alloc_it = stack_to_allocation.find(std::pair(allocation.frame_index, thread_id));
        if (alloc_it == stack_to_allocation.end()) {
            Allocation new_alloc = allocation;
            new_alloc.size = range.size();
            stack_to_allocation.insert(
                    alloc_it,
                    std::pair(std::pair(allocation.frame_index, thread_id), new_alloc));
        } else {
            alloc_it->second.size += range.size();
            alloc_it->second.n_allocations += 1;
        }
    }

    return stack_to_allocation;
}

}  // unnamed namespace

Interval::Interval(uintptr_t begin, uintptr_t end)
: begin(begin)
, end(end){};

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
}

reduced_snapshot_map_t
SnapshotAllocationAggregator::getSnapshotAllocations(bool merge_threads)
{
    return reduceSnapshotAllocations(merge_threads, d_interval_tree, d_ptr_to_allocation);
}

bool
StreamingAllocationAggregator::atHighWaterMark() const
{
    if (d_delta_freed_size == 0 && d_delta_allocated_size == 0) {
        assert(0 == d_delta_freed_ranges.size());
        assert(0 == d_delta_allocated_ranges.size());
        assert(0 == d_delta_freed_ptrs.size());
        assert(0 == d_delta_allocated_ptrs.size());
        return true;
    }
    return false;
}

void
StreamingAllocationAggregator::applyDeltaToSnapshot(
        IntervalTree<Allocation>* allocated_ranges,
        std::unordered_map<uintptr_t, Allocation>* allocated_ptrs)
{
    for (auto& address : d_delta_freed_ptrs) {
        allocated_ptrs->erase(address);
    }
    for (auto& [interval, _] : d_delta_freed_ranges) {
        allocated_ranges->removeInterval(interval.begin, interval.size());
    }
    for (auto& [_, allocation] : d_delta_allocated_ptrs) {
        allocated_ptrs->insert_or_assign(allocation.address, allocation);
    }
    for (auto& [_, allocation] : d_delta_allocated_ranges) {
        allocated_ranges->addInterval(allocation.address, allocation.size, allocation);
    }
}

void
StreamingAllocationAggregator::resetDelta()
{
    d_delta_allocated_size = 0;
    d_delta_freed_size = 0;
    d_delta_freed_ranges.clear();
    d_delta_freed_ptrs.clear();
    d_delta_allocated_ranges.clear();
    d_delta_allocated_ptrs.clear();
}

void
StreamingAllocationAggregator::addAllocationWhileAtHighWaterMark(const Allocation& allocation)
{
    assert(atHighWaterMark());
    size_t index = d_allocations_seen++;
    switch (hooks::allocatorKind(allocation.allocator)) {
        case hooks::AllocatorKind::SIMPLE_ALLOCATOR: {
            d_high_water_mark_ptrs[allocation.address] = allocation;
            d_high_water_mark_index = index;
            d_high_water_mark_memory += allocation.size;
        } break;
        case hooks::AllocatorKind::RANGED_ALLOCATOR: {
            d_high_water_mark_ranges.addInterval(allocation.address, allocation.size, allocation);
            d_high_water_mark_index = index;
            d_high_water_mark_memory += allocation.size;
        } break;
        case hooks::AllocatorKind::SIMPLE_DEALLOCATOR: {
            // If the ptr was in the high water mark, start a delta.
            auto it = d_high_water_mark_ptrs.find(allocation.address);
            if (it != d_high_water_mark_ptrs.end()) {
                if (it->second.size) {
                    d_delta_freed_ptrs.insert(allocation.address);
                    d_delta_freed_size += it->second.size;
                    assert(!atHighWaterMark());
                } else {
                    // Special case: if the freed pointer was for a 0 byte
                    // allocation, we're still at the high water mark.
                    d_high_water_mark_ptrs.erase(it);
                    d_high_water_mark_index = index;
                }
            }
        } break;
        case hooks::AllocatorKind::RANGED_DEALLOCATOR: {
            // If the range being freed overlaps with any ranges included in
            // the high water mark, start a delta.
            auto overlap =
                    d_high_water_mark_ranges.findIntersection(allocation.address, allocation.size);
            for (auto& interval : overlap) {
                d_delta_freed_ranges.addInterval(interval.begin, interval.size(), 0);
                d_delta_freed_size += interval.size();
            }
        } break;
    }
}

void
StreamingAllocationAggregator::addAllocationWhileNotAtHighWaterMark(const Allocation& allocation)
{
    assert(!atHighWaterMark());
    size_t index = d_allocations_seen++;
    switch (hooks::allocatorKind(allocation.allocator)) {
        case hooks::AllocatorKind::SIMPLE_ALLOCATOR: {
            d_delta_allocated_ptrs[allocation.address] = allocation;
            d_delta_allocated_size += allocation.size;
        } break;
        case hooks::AllocatorKind::RANGED_ALLOCATOR: {
            d_delta_allocated_ranges.addInterval(allocation.address, allocation.size, allocation);
            d_delta_allocated_size += allocation.size;
        } break;
        case hooks::AllocatorKind::SIMPLE_DEALLOCATOR: {
            auto it = d_delta_allocated_ptrs.find(allocation.address);
            if (it != d_delta_allocated_ptrs.end()) {
                // This ptr was allocated after forking the delta.
                assert(d_delta_allocated_size >= it->second.size);
                d_delta_allocated_size -= it->second.size;
                d_delta_allocated_ptrs.erase(it);
            } else if (d_delta_freed_ptrs.count(allocation.address)) {
                // Our delta already holds a free for this address. This can
                // happen if, after being freed, it was reallocated by a call
                // that we didn't track, then freed by a call that we did. In
                // particular, this can happen if it's allocated with the
                // recursion guard enabled and freed with it disabled. For
                // instance, the allocation for our TLS vector happens while
                // the recursion guard is set, but the deallocation happens as
                // our thread is dying, after the recursion guard is unset.
            } else {
                // This ptr was allocated before forking the delta.
                // Check if it was part of the high water mark.
                auto it = d_high_water_mark_ptrs.find(allocation.address);
                if (it != d_high_water_mark_ptrs.end()) {
                    // It was part of the high water mark.
                    d_delta_freed_ptrs.insert(allocation.address);
                    d_delta_freed_size += it->second.size;
                } else {
                    // Ignore it. This must be a free of something allocated
                    // before tracking started.
                }
            }
        } break;
        case hooks::AllocatorKind::RANGED_DEALLOCATOR: {
            // Handle portions of the range allocated since forking the delta.
            auto allocated_since_delta_began =
                    d_delta_allocated_ranges.findIntersection(allocation.address, allocation.size);

            for (auto& interval : allocated_since_delta_began) {
                d_delta_allocated_ranges.removeInterval(interval.begin, interval.size());
                assert(d_delta_allocated_size >= interval.size());
                d_delta_allocated_size -= interval.size();
            }

            // Handle portions of the range included in the high water mark.
            IntervalTree<int> allocated_before_delta_began;
            allocated_before_delta_began.addInterval(allocation.address, allocation.size, 0);
            for (auto& interval : allocated_since_delta_began) {
                allocated_before_delta_began.removeInterval(interval.begin, interval.size());
            }

            size_t deltaFreedIntervalsSizeBefore = d_delta_freed_ranges.size();
            for (auto& [old_interval, _] : allocated_before_delta_began) {
                auto included_in_high_water_mark = d_high_water_mark_ranges.findIntersection(
                        old_interval.begin,
                        old_interval.size());

                for (auto& interval : included_in_high_water_mark) {
                    d_delta_freed_ranges.removeInterval(interval.begin, interval.size());
                    d_delta_freed_ranges.addInterval(interval.begin, interval.size(), 0);
                }
            }
            size_t deltaFreedIntervalsSizeAfter = d_delta_freed_ranges.size();
            d_delta_freed_size += (deltaFreedIntervalsSizeAfter - deltaFreedIntervalsSizeBefore);
        } break;
    }

    if (d_delta_allocated_size >= d_delta_freed_size) {
        // New high water mark!
        d_high_water_mark_index = index;
        d_high_water_mark_memory += (d_delta_allocated_size - d_delta_freed_size);
        applyDeltaToSnapshot(&d_high_water_mark_ranges, &d_high_water_mark_ptrs);
        resetDelta();
        assert(atHighWaterMark());
    }
}

void
StreamingAllocationAggregator::addAllocation(const Allocation& allocation)
{
    if (atHighWaterMark()) {
        addAllocationWhileAtHighWaterMark(allocation);
    } else {
        addAllocationWhileNotAtHighWaterMark(allocation);
    }
}

reduced_snapshot_map_t
StreamingAllocationAggregator::getHighWaterMarkAllocations(bool merge_threads)
{
    return reduceSnapshotAllocations(merge_threads, d_high_water_mark_ranges, d_high_water_mark_ptrs);
}

reduced_snapshot_map_t
StreamingAllocationAggregator::getLeakedAllocations(bool merge_threads)
{
    auto ranges = d_high_water_mark_ranges;
    auto ptrs = d_high_water_mark_ptrs;
    applyDeltaToSnapshot(&ranges, &ptrs);
    return reduceSnapshotAllocations(merge_threads, ranges, ptrs);
}

HighWaterMark
StreamingAllocationAggregator::getHighWaterMark() const noexcept
{
    return {d_high_water_mark_index, d_high_water_mark_memory};
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
