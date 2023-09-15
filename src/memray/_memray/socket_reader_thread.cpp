#include "socket_reader_thread.h"

#include <iostream>

namespace memray::socket_thread {

void
BackgroundSocketReader::backgroundThreadWorker()
{
    while (true) {
        if (d_stop_thread) {
            break;
        }

        const auto record_type = d_record_reader->nextRecord();

        if (d_stop_thread) {
            break;
        }

        switch (record_type) {
            case RecordResult::ALLOCATION_RECORD: {
                std::lock_guard<std::mutex> lock(d_mutex);
                const auto& it = d_record_reader->getLatestAllocation();
                d_aggregator.addAllocation(it);
                stats_aggregator.addAllocation(it, d_record_reader->getLatestPythonFrameId(it));
            } break;

            case RecordResult::MEMORY_RECORD: {
            } break;

            case RecordResult::AGGREGATED_ALLOCATION_RECORD: {
                // This should never happen. We checked the source format in
                // the constructor, and RecordReader should never return
                // records that don't match the source format.
                std::cerr << "BUG: AGGREGATED_ALLOCATION_RECORD from ALL_ALLOCATIONS input" << std::endl;
                abort();
            } break;

            case RecordResult::MEMORY_SNAPSHOT: {
                // As above.
                std::cerr << "BUG: MEMORY_SNAPSHOT from ALL_ALLOCATIONS input" << std::endl;
                abort();
            } break;

            case RecordResult::END_OF_FILE:
            case RecordResult::ERROR: {
                d_stop_thread = true;
            } break;
        }
    }
}

BackgroundSocketReader::BackgroundSocketReader(std::shared_ptr<api::RecordReader> reader)
: d_record_reader(reader)
{
    if (d_record_reader->getHeader().file_format != api::FileFormat::ALL_ALLOCATIONS) {
        throw std::runtime_error("BackgroundSocketReader only supports ALL_ALLOCATIONS");
    }
}

void
BackgroundSocketReader::start()
{
    d_thread = std::thread(&BackgroundSocketReader::backgroundThreadWorker, this);
}

BackgroundSocketReader::~BackgroundSocketReader()
{
    d_record_reader->close();
    d_stop_thread = true;
    d_thread.join();
}

PyObject*
BackgroundSocketReader::Py_GetSnapshotAllocationRecords(bool merge_threads)
{
    api::reduced_snapshot_map_t stack_to_allocation;
    {
        std::lock_guard<std::mutex> lock(d_mutex);
        stack_to_allocation = d_aggregator.getSnapshotAllocations(merge_threads);
    }

    return api::Py_ListFromSnapshotAllocationRecords(stack_to_allocation);
}

PyObject*
BackgroundSocketReader::Py_GetSnapshotAllocationRecordsAndStatsData(bool merge_threads, int largest_num)
{
    api::reduced_snapshot_map_t stack_to_allocation;

    std::unordered_map<size_t, uint64_t> cnt_by_size;
    std::unordered_map<int, uint64_t> cnt_by_alloc;
    std::vector<std::pair<uint64_t, std::optional<memray::tracking_api::frame_id_t>>> top_size;
    std::vector<std::pair<uint64_t, std::optional<memray::tracking_api::frame_id_t>>> top_cnt;
    std::uint64_t total_size;
    std::uint64_t total_cnt;
    {
        std::lock_guard<std::mutex> lock(d_mutex);
        stack_to_allocation = d_aggregator.getSnapshotAllocations(merge_threads);
        cnt_by_size = stats_aggregator.allocationCountBySize();
        cnt_by_alloc = stats_aggregator.allocationCountByAllocator();
        top_size = stats_aggregator.topLocationsBySize(largest_num);
        top_cnt = stats_aggregator.topLocationsByCount(largest_num);
        total_cnt = stats_aggregator.totalAllocations();
        total_size = stats_aggregator.totalBytesAllocated();
    }
    PyObject* snaps = api::Py_ListFromSnapshotAllocationRecords(stack_to_allocation);
    PyObject* stats =
            Py_GetStatsData(cnt_by_size, cnt_by_alloc, top_size, top_cnt, total_size, total_cnt);
    PyObject* result = PyTuple_Pack(2, snaps, stats);
    Py_XDECREF(snaps);
    Py_XDECREF(stats);
    return result;
}

bool
BackgroundSocketReader::is_active() const
{
    return !d_stop_thread;
}

PyObject*
BackgroundSocketReader::Py_GetStatsData(
        const std::unordered_map<size_t, uint64_t>& cnt_by_size,
        const std::unordered_map<int, uint64_t>& cnt_by_alloc,
        std::vector<std::pair<uint64_t, std::optional<memray::tracking_api::frame_id_t>>>& top_size,
        std::vector<std::pair<uint64_t, std::optional<memray::tracking_api::frame_id_t>>>& top_cnt,
        std::uint64_t total_size,
        std::uint64_t total_cnt)
{
    PyObject* result = PyList_New(0);
    if (result == nullptr) {
        return nullptr;
    }

    PyObject* py_cnt_by_size = PyDict_New();
    if (py_cnt_by_size == nullptr) {
        Py_XDECREF(result);
        return nullptr;
    }
    for (const auto& it : cnt_by_size) {
        PyObject* pk = PyLong_FromSize_t(it.first);
        PyObject* pv = PyLong_FromUnsignedLong(it.second);
        PyDict_SetItem(py_cnt_by_size, pk, pv);
        Py_XDECREF(pk);
        Py_XDECREF(pv);
    }
    PyList_Append(result, py_cnt_by_size);
    Py_XDECREF(py_cnt_by_size);

    PyObject* py_cnt_by_alloc = PyDict_New();
    if (py_cnt_by_alloc == nullptr) {
        Py_XDECREF(result);
        return nullptr;
    }
    for (const auto& it : cnt_by_alloc) {
        PyObject* pk = PyLong_FromLong(it.first);
        PyObject* pv = PyLong_FromUnsignedLong(it.second);
        PyDict_SetItem(py_cnt_by_alloc, pk, pv);
        Py_XDECREF(pk);
        Py_XDECREF(pv);
    }
    PyList_Append(result, py_cnt_by_alloc);
    Py_XDECREF(py_cnt_by_alloc);

    PyObject* py_top_size = PyList_New(0);
    if (py_top_size == nullptr) {
        Py_XDECREF(result);
        return nullptr;
    }
    for (const auto& it : top_size) {
        //        PyObject* pk = PyLong_FromSize_t(it.second.value_or(0));
        //        PyObject * pk = d_record_reader ->Py_GetFrame(it.second.value_or(0));
        PyObject* pk;
        try {  // todo: optimize
            pk = d_record_reader->Py_GetFrame(it.second.value_or(0));
        } catch (std::exception& e) {
            PyObject* function = PyUnicode_FromString("");
            PyObject* file = PyUnicode_FromString("");
            PyObject* line = PyLong_FromLong(0);
            pk = PyTuple_Pack(3, function, file, line);
            Py_XDECREF(function);
            Py_XDECREF(file);
            Py_XDECREF(line);
        };
        PyObject* pv = PyLong_FromSize_t(it.first);
        PyObject* pair = PyTuple_Pack(2, pk, pv);
        PyList_Append(py_top_size, pair);
        Py_XDECREF(pk);
        Py_XDECREF(pv);
        Py_XDECREF(pair);
    }
    PyList_Append(result, py_top_size);
    Py_XDECREF(py_top_size);

    PyObject* py_top_cnt = PyList_New(0);
    if (py_top_cnt == nullptr) {
        Py_XDECREF(result);
        return nullptr;
    }
    for (const auto& it : top_cnt) {
        //        PyObject* pk = PyLong_FromSize_t(it.second.value_or(0));
        //        PyObject * pk = d_record_reader ->Py_GetFrame(it.second.value_or(0));
        PyObject* pk;
        try {  // todo: optimize
            pk = d_record_reader->Py_GetFrame(it.second.value_or(0));
        } catch (std::exception& e) {
            PyObject* function = PyUnicode_FromString("");
            PyObject* file = PyUnicode_FromString("");
            PyObject* line = PyLong_FromLong(0);
            pk = PyTuple_Pack(3, function, file, line);
            Py_XDECREF(function);
            Py_XDECREF(file);
            Py_XDECREF(line);
        };
        PyObject* pv = PyLong_FromSize_t(it.first);
        PyObject* pair = PyTuple_Pack(2, pk, pv);
        PyList_Append(py_top_cnt, pair);
        Py_XDECREF(pk);
        Py_XDECREF(pv);
        Py_XDECREF(pair);
    }
    PyList_Append(result, py_top_cnt);
    Py_XDECREF(py_top_cnt);

    PyObject* py_total_size = PyLong_FromUnsignedLong(total_size);
    PyObject* py_total_cnt = PyLong_FromUnsignedLong(total_cnt);
    PyList_Append(result, py_total_size);
    PyList_Append(result, py_total_cnt);
    Py_XDECREF(py_total_size);
    Py_XDECREF(py_total_cnt);

    return result;
}

}  // namespace memray::socket_thread
