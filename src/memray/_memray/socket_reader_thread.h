#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <atomic>
#include <memory>
#include <mutex>
#include <thread>

#include "record_reader.h"
#include "records.h"
#include "snapshot.h"

namespace memray::socket_thread {

class BackgroundSocketReader
{
  private:
    using RecordResult = api::RecordReader::RecordResult;

    std::atomic<bool> d_stop_thread{false};
    std::mutex d_mutex;
    std::shared_ptr<api::RecordReader> d_record_reader;

    api::SnapshotAllocationAggregator d_aggregator;
    api::AllocationStatsAggregator stats_aggregator;
    std::thread d_thread;

    void backgroundThreadWorker();

  public:
    BackgroundSocketReader(BackgroundSocketReader& other) = delete;
    BackgroundSocketReader(BackgroundSocketReader&& other) = delete;
    void operator=(const BackgroundSocketReader&) = delete;
    void operator=(BackgroundSocketReader&&) = delete;

    explicit BackgroundSocketReader(std::shared_ptr<api::RecordReader> reader);
    ~BackgroundSocketReader();

    void start();
    bool is_active() const;
    PyObject* Py_GetSnapshotAllocationRecords(bool merge_threads);
    PyObject* Py_GetStatsData(
            const std::unordered_map<size_t, uint64_t>& cnt_by_size,
            const std::unordered_map<int, uint64_t>& cnt_by_alloc,
            std::vector<std::pair<uint64_t, std::optional<memray::tracking_api::frame_id_t>>>& top_size,
            std::vector<std::pair<uint64_t, std::optional<memray::tracking_api::frame_id_t>>>& top_cnt,
            std::uint64_t total_size,
            std::uint64_t total_cnt);
    PyObject* Py_GetSnapshotAllocationRecordsAndStatsData(bool merge_threads, int largest_num);
};

}  // namespace memray::socket_thread
