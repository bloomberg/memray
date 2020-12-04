#include <cassert>

#include "guards.h"
#include "record_writer.h"
#include "records.h"

namespace pensieve::api {

const int RECORD_BUFFER_SIZE = 100;

RecordWriter::RecordWriter(serializer_ptr_t serializer)
: d_serializer(std::move(serializer))
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
    {
        std::scoped_lock<std::mutex> lock(d_write_lock);
        d_flush_signal.notify_one();
    }
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
    size_t elements;
    {
        std::lock_guard<std::mutex> lock(d_write_lock);
        d_record_buffer->emplace_back(record);
        elements = d_record_buffer->size();
    }
    if (elements >= RECORD_BUFFER_SIZE) {
        std::scoped_lock<std::mutex> lock(d_write_lock);
        d_flush_signal.notify_one();
    }
}

void
RecordWriter::flush(records_ptr_t& records)
{
    RecursionGuard guard;
    std::scoped_lock<std::mutex> flush_lock(d_flush_lock);
    for (const auto& elem : *records) {
        d_serializer->write(elem);
    }
    records->clear();
}

void
RecordWriter::flush()
{
    RecursionGuard guard;
    std::unique_lock<std::mutex> lock(d_write_lock);
    flush(d_record_buffer);
    flush(d_secondary_buffer);
}

}  // namespace pensieve::api
