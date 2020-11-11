#include <cassert>

#include "guards.h"
#include "record_writer.h"
#include "records.h"

namespace pensieve::api {

const int RECORD_BUFFER_SIZE = 100;

StreamSerializer::StreamSerializer(std::ostream& outputStream)
: d_outStream(outputStream)
{
}

void
StreamSerializer::write(const tracking_api::AllocationRecord& record)
{
    d_outStream << "Process ID: [" << record.pid << "] "
                << "Thread ID: [" << record.tid << "] "
                << "Allocation size: [" << record.size << "] "
                << "Allocation address: [" << std::hex << record.address << std::dec << "] "
                << record.stacktrace.size() << " total frames: ";
    for (const auto& frame : record.stacktrace) {
        d_outStream << "File name: [" << frame.filename << "] ";
        d_outStream << "Line number: [" << frame.lineno << "] ";
        d_outStream << "Function: [" << frame.function_name << "] ";
    }
    d_outStream << std::endl;
}

void
InMemorySerializer::write(const tracking_api::AllocationRecord& record)
{
    d_records.emplace_back(record);
}

void
InMemorySerializer::clear()
{
    d_records.clear();
}
const InMemorySerializer::records_t&
InMemorySerializer::getRecords()
{
    return d_records;
}

RecordWriter::RecordWriter(Serializer& serializer)
: d_serializer(serializer)
, d_record_buffer(std::make_unique<records_t>())
, d_secondary_buffer(std::make_unique<records_t>())
, d_io_thread(std::thread(&RecordWriter::ioHandler, this))
{
}

RecordWriter::~RecordWriter()
{
    stop();
    assert(d_record_buffer->empty());
    assert(d_secondary_buffer->empty());
}

void
RecordWriter::stop()
{
    RecursionGuard guard;
    d_is_stopping = true;
    d_flush_signal.notify_one();
    d_io_thread.join();
}

void
RecordWriter::ioHandler()
{
    RecursionGuard::isActive = true;
    while (true) {
        std::unique_lock<std::mutex> lock(d_write_lock);

        d_flush_signal.wait(lock, [this] {
            return d_is_stopping || d_record_buffer->size() >= RECORD_BUFFER_SIZE;
        });

        if (d_is_stopping) {
            flush(d_record_buffer);
            return;
        }

        {
            // Protect the secondary buffer from swapping before a previous flush() has completed
            std::scoped_lock<std::mutex> flush_lock(d_flush_lock);
            assert(d_secondary_buffer->empty());
            std::swap<records_ptr_t>(d_secondary_buffer, d_record_buffer);
        }
        lock.unlock();
        flush(d_secondary_buffer);
    }
}

void
RecordWriter::collect(const tracking_api::AllocationRecord& record)
{
    {
        std::lock_guard<std::mutex> lock(d_write_lock);
        d_record_buffer->emplace_back(record);
    }
    if (d_record_buffer->size() >= RECORD_BUFFER_SIZE) {
        d_flush_signal.notify_one();
    }
}

void
RecordWriter::flush(records_ptr_t& records)
{
    RecursionGuard guard;
    std::scoped_lock<std::mutex> flush_lock(d_flush_lock);
    for (const auto& elem : *records) {
        d_serializer.write(elem);
    }
    records->clear();
}

void
RecordWriter::flush()
{
    RecursionGuard guard;
    std::unique_lock<std::mutex> lock(d_write_lock);
    flush(d_record_buffer);
}

}  // namespace pensieve::api
