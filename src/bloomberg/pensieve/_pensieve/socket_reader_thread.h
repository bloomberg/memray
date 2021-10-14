#pragma once

#include <atomic>
#include <memory>
#include <mutex>
#include <thread>

#include "Python.h"
#include "record_reader.h"
#include "snapshot.h"

namespace pensieve::socket_thread {

class BackgroundSocketReader
{
  private:
    std::atomic<bool> d_stop_thread{false};
    std::mutex d_mutex;
    std::shared_ptr<api::RecordReader> d_record_reader;

    api::SnapshotAllocationAggregator d_aggregator;
    std::thread d_thread;

    void backgroundThreadWorker();

  public:
    explicit BackgroundSocketReader(std::shared_ptr<api::RecordReader> reader);
    ~BackgroundSocketReader();

    void start();
    PyObject* Py_GetSnapshotAllocationRecords(bool merge_threads);
};

}  // namespace pensieve::socket_thread
