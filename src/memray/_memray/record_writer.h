#pragma once

#include <cerrno>
#include <climits>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <type_traits>
#include <unistd.h>

#include "records.h"
#include "sink.h"

namespace memray::tracking_api {
class RecordWriter
{
  public:
    explicit RecordWriter(
            std::unique_ptr<memray::io::Sink> sink,
            const std::string& command_line,
            bool native_traces);

    RecordWriter(RecordWriter& other) = delete;
    RecordWriter(RecordWriter&& other) = delete;
    void operator=(const RecordWriter&) = delete;
    void operator=(RecordWriter&&) = delete;

    template<typename T>
    bool inline writeSimpleType(T&& item);
    bool inline writeString(const char* the_string);
    template<typename T>
    bool inline writeRecord(const RecordType& token, const T& item);
    template<typename T>
    bool inline writeRecordUnsafe(const RecordType& token, const T& item);
    bool writeHeader(bool seek_to_start);

    std::unique_lock<std::mutex> acquireLock();
    std::unique_ptr<RecordWriter> cloneInChildProcess();

  private:
    // Data members
    int d_version{CURRENT_HEADER_VERSION};
    std::unique_ptr<memray::io::Sink> d_sink;
    std::mutex d_mutex;
    HeaderRecord d_header{};
    TrackerStats d_stats{};
};

template<typename T>
bool inline RecordWriter::writeSimpleType(T&& item)
{
    return d_sink->writeAll(reinterpret_cast<const char*>(&item), sizeof(item));
};

bool inline RecordWriter::writeString(const char* the_string)
{
    return d_sink->writeAll(the_string, strlen(the_string) + 1);
}

template<typename T>
bool inline RecordWriter::writeRecord(const RecordType& token, const T& item)
{
    std::lock_guard<std::mutex> lock(d_mutex);
    return writeRecordUnsafe(token, item);
}

template<typename T>
bool inline RecordWriter::writeRecordUnsafe(const RecordType& token, const T& item)
{
    static_assert(
            std::is_trivially_copyable<T>::value,
            "Called writeRecord on binary records which cannot be trivially copied");

    if (token == RecordType::ALLOCATION || token == RecordType::ALLOCATION_WITH_NATIVE) {
        d_stats.n_allocations += 1;
    }
    return d_sink->writeAll(reinterpret_cast<const char*>(&token), sizeof(RecordType))
           && d_sink->writeAll(reinterpret_cast<const char*>(&item), sizeof(T));
}

template<>
bool inline RecordWriter::writeRecordUnsafe(const RecordType& token, const pyrawframe_map_val_t& item)
{
    d_stats.n_frames += 1;
    return writeSimpleType(token) && writeSimpleType(item.first)
           && writeString(item.second.function_name) && writeString(item.second.filename)
           && writeSimpleType(item.second.lineno);
}

template<>
bool inline RecordWriter::writeRecordUnsafe(const RecordType& token, const SegmentHeader& item)
{
    return writeSimpleType(token) && writeString(item.filename) && writeSimpleType(item.num_segments)
           && writeSimpleType(item.addr);
}

template<>
bool inline RecordWriter::writeRecordUnsafe(const RecordType& token, const ThreadRecord& record)
{
    return writeSimpleType(token) && writeSimpleType(record.tid) && writeString(record.name);
}

}  // namespace memray::tracking_api
