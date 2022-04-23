#include "socket_reader_thread.h"

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
                d_aggregator.addAllocation(d_record_reader->getLatestAllocation());
                break;
            }

            case RecordResult::MEMORY_RECORD: {
                break;
            }
            case RecordResult::END_OF_FILE:
            case RecordResult::ERROR: {
                d_stop_thread = true;
                return;
            }
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

bool
BackgroundSocketReader::is_active() const
{
    return !d_stop_thread;
}

}  // namespace memray::socket_thread
