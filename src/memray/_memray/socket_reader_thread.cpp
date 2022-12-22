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
                d_aggregator.addAllocation(d_record_reader->getLatestAllocation());
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

bool
BackgroundSocketReader::is_active() const
{
    return !d_stop_thread;
}

}  // namespace memray::socket_thread
