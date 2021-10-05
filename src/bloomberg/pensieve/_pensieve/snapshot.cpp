#include <numeric>

#include "snapshot.h"

namespace pensieve::api {

SnapshotAllocationAggregator::SnapshotAllocationAggregator(const allocations_t& records)
: d_records(records)
{
}

void
SnapshotAllocationAggregator::addAllocation(const Allocation& allocation)
{
    switch (hooks::allocatorKind(allocation.record.allocator)) {
        case hooks::AllocatorKind::SIMPLE_ALLOCATOR: {
            d_ptr_to_allocation[allocation.record.address] = d_index;
            break;
        }
        case hooks::AllocatorKind::SIMPLE_DEALLOCATOR: {
            auto it = d_ptr_to_allocation.find(allocation.record.address);
            if (it != d_ptr_to_allocation.end()) {
                d_ptr_to_allocation.erase(it);
            }
            break;
        }
        case hooks::AllocatorKind::RANGED_ALLOCATOR: {
            auto record = allocation.record;
            d_interval_tree.add(record.address, record.size, allocation);
            break;
        }
        case hooks::AllocatorKind::RANGED_DEALLOCATOR: {
            auto record = allocation.record;
            d_interval_tree.remove(record.address, record.size);
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
        const Allocation& record = d_records[it.second];
        const thread_id_t thread_id = merge_threads ? NO_THREAD_INFO : record.record.tid;
        auto alloc_it = stack_to_allocation.find(std::pair(record.frame_index, thread_id));
        if (alloc_it == stack_to_allocation.end()) {
            stack_to_allocation.insert(
                    alloc_it,
                    std::pair(std::pair(record.frame_index, thread_id), record));
        } else {
            alloc_it->second.record.size += record.record.size;
            alloc_it->second.n_allocations += 1;
        }
    }

    // Process ranged allocations. As there can be partial deallocations in mmap'd regions,
    // we update the allocation to reflect the actual size at the peak, based on the lengths
    // of the ranges in the interval tree.
    for (const auto& [range, allocation] : d_interval_tree) {
        const thread_id_t thread_id = merge_threads ? NO_THREAD_INFO : allocation.record.tid;
        auto alloc_it = stack_to_allocation.find(std::pair(allocation.frame_index, thread_id));
        if (alloc_it == stack_to_allocation.end()) {
            Allocation new_alloc = allocation;
            new_alloc.record.size = range.size();
            stack_to_allocation.insert(
                    alloc_it,
                    std::pair(std::pair(allocation.frame_index, thread_id), new_alloc));
        } else {
            alloc_it->second.record.size += range.size();
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

    SnapshotAllocationAggregator aggregator(records);

    std::for_each(records.cbegin(), records.cbegin() + snapshot_index + 1, [&](auto& record) {
        aggregator.addAllocation(record);
    });

    return aggregator.getSnapshotAllocations(merge_threads);
}

HighWatermark
getHighWatermark(const allocations_t& records)
{
    HighWatermark result;
    size_t current_memory = 0;
    std::unordered_map<uintptr_t, size_t> ptr_to_allocation{};
    pensieve::IntervalTree<Allocation> mmap_intervals;

    auto update_peak = [&](allocations_t::const_iterator records_it) {
        if (current_memory >= result.peak_memory) {
            result.index = records_it - records.cbegin();
            result.peak_memory = current_memory;
        }
    };

    for (auto records_it = records.cbegin(); records_it != records.cend(); records_it++) {
        switch (hooks::allocatorKind(records_it->record.allocator)) {
            case hooks::AllocatorKind::SIMPLE_ALLOCATOR: {
                current_memory += records_it->record.size;
                update_peak(records_it);
                ptr_to_allocation[records_it->record.address] = records_it - records.begin();
                break;
            }
            case hooks::AllocatorKind::SIMPLE_DEALLOCATOR: {
                auto it = ptr_to_allocation.find(records_it->record.address);
                if (it != ptr_to_allocation.end()) {
                    current_memory -= records[it->second].record.size;
                    ptr_to_allocation.erase(it);
                }
                break;
            }
            case hooks::AllocatorKind::RANGED_ALLOCATOR: {
                mmap_intervals.add(records_it->record.address, records_it->record.size, *records_it);
                current_memory += records_it->record.size;
                update_peak(records_it);
                break;
            }
            case hooks::AllocatorKind::RANGED_DEALLOCATOR: {
                const auto address = records_it->record.address;
                const auto size = records_it->record.size;
                const auto removed = mmap_intervals.remove(address, size);

                if (!removed.has_value()) {
                    break;
                }
                size_t removed_size = std::accumulate(
                        removed.value().begin(),
                        removed.value().cend(),
                        0,
                        [](size_t sum, const std::pair<Range, Allocation>& range) {
                            return sum + range.first.size();
                        });
                current_memory -= removed_size;
                update_peak(records_it);
                break;
            }
        }
    }
    return result;
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

}  // namespace pensieve::api
