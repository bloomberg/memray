#include "socket_reader_thread.h"

namespace pensieve::socket_thread {

void
BackgroundSocketReader::backgroundThreadWorker()
{
    api::Allocation record;
    bool got_record = false;
    while (true) {
        if (d_stop_thread) {
            break;
        }

        got_record = d_record_reader->nextAllocationRecord(&record);

        if (d_stop_thread) {
            break;
        }

        if (got_record) {
            std::lock_guard<std::mutex> lock(d_mutex);
            d_aggregator.addAllocation(record);
        }
    }
}

BackgroundSocketReader::BackgroundSocketReader(std::shared_ptr<api::RecordReader> reader)
: d_record_reader(reader)
{
}

void
BackgroundSocketReader::start()
{
    d_thread = std::thread(&BackgroundSocketReader::backgroundThreadWorker, this);
}

BackgroundSocketReader::~BackgroundSocketReader()
{
    d_stop_thread = true;
    d_thread.join();
}

PyObject*
BackgroundSocketReader::Py_GetSnapshotAllocationRecords(bool merge_threads)
{
    std::lock_guard<std::mutex> lock(d_mutex);
    const auto stack_to_allocation = d_aggregator.getSnapshotAllocations(merge_threads);
    return api::Py_ListFromSnapshotAllocationRecords(stack_to_allocation);
}

}  // namespace pensieve::socket_thread
