#pragma once

#include <atomic>
#include <condition_variable>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

#include "guards.h"
#include "records.h"

namespace pensieve::api {

class Serializer
{
  public:
    virtual void write(const tracking_api::AllocationRecord& record) = 0;
};

class StreamSerializer : public Serializer
{
  public:
    explicit StreamSerializer(std::ostream& outputStream);
    ~StreamSerializer() = default;

    StreamSerializer(StreamSerializer&) = delete;
    StreamSerializer& operator=(StreamSerializer&) = delete;

    void write(const tracking_api::AllocationRecord& record) override;

  private:
    std::ostream& d_outStream;
};

class InMemorySerializer : public Serializer
{
  public:
    typedef std::vector<tracking_api::AllocationRecord> records_t;

    InMemorySerializer() = default;
    ~InMemorySerializer() = default;

    InMemorySerializer(InMemorySerializer&) = delete;
    InMemorySerializer& operator=(InMemorySerializer&) = delete;

    void write(const tracking_api::AllocationRecord& record) override;

    void clear();
    const records_t& getRecords();

  private:
    records_t d_records;
};

class RecordWriter
{
  public:
    typedef std::vector<tracking_api::AllocationRecord> records_t;
    typedef std::unique_ptr<records_t> records_ptr_t;
    typedef std::unique_ptr<Serializer> serializer_ptr_t;

    explicit RecordWriter(serializer_ptr_t serializer);
    ~RecordWriter();

    void collect(const tracking_api::AllocationRecord& record);
    void stop();
    void flush();

  private:
    void ioHandler();
    void flush(records_ptr_t& queue);

    serializer_ptr_t d_serializer;
    records_ptr_t d_record_buffer;
    records_ptr_t d_secondary_buffer;
    std::condition_variable d_flush_signal;
    std::mutex d_write_lock;
    std::mutex d_flush_lock;
    std::atomic<bool> d_is_stopping{false};
    std::thread d_io_thread;
};

}  // namespace pensieve::api
