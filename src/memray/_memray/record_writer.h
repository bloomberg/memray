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
    bool inline writeVarint(size_t val);
    template<typename T>
    bool inline writeRecord(const RecordType& token, const T& item);
    template<typename T>
    bool inline writeThreadSpecificRecord(const RecordType& token, thread_id_t tid, const T& item);
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
    thread_id_t d_lastTid{};
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

bool inline RecordWriter::writeVarint(size_t rest)
{
    unsigned char next_7_bits = rest & 0x7f;
    rest >>= 7;
    while (rest) {
        next_7_bits |= 0x80;
        if (!writeSimpleType(next_7_bits)) {
            return false;
        }
        next_7_bits = rest & 0x7f;
        rest >>= 7;
    }

    return writeSimpleType(next_7_bits);
}

template<typename T>
bool inline RecordWriter::writeRecord(const RecordType& token, const T& item)
{
    std::lock_guard<std::mutex> lock(d_mutex);
    return writeRecordUnsafe(token, item);
}

template<typename T>
bool inline RecordWriter::writeThreadSpecificRecord(
        const RecordType& token,
        thread_id_t tid,
        const T& item)
{
    std::lock_guard<std::mutex> lock(d_mutex);
    if (d_lastTid != tid) {
        d_lastTid = tid;
        if (!writeRecordUnsafe(RecordType::CONTEXT_SWITCH, tid)) {
            return false;
        }
    }
    return writeRecordUnsafe(token, item);
}

template<typename T>
bool inline RecordWriter::writeRecordUnsafe(const RecordType& token, const T& item)
{
    static_assert(
            std::is_trivially_copyable<T>::value,
            "Called writeRecord on binary records which cannot be trivially copied");

    return d_sink->writeAll(reinterpret_cast<const char*>(&token), sizeof(RecordType))
           && d_sink->writeAll(reinterpret_cast<const char*>(&item), sizeof(T));
}

template<>
bool inline RecordWriter::writeRecordUnsafe(const RecordType& token, const AllocationRecord& record)
{
    d_stats.n_allocations += 1;
    return writeSimpleType(RecordTypeAndFlags{token, static_cast<unsigned char>(record.allocator)})
           && writeSimpleType(record.address) && writeVarint(record.size);
}

template<>
bool inline RecordWriter::writeRecordUnsafe(
        const RecordType& token,
        const NativeAllocationRecord& record)
{
    d_stats.n_allocations += 1;
    return writeSimpleType(RecordTypeAndFlags{token, static_cast<unsigned char>(record.allocator)})
           && writeSimpleType(record.address) && writeVarint(record.size)
           && writeVarint(record.native_frame_id);
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
    return writeSimpleType(token) && writeString(record.name);
}

template<>
bool inline RecordWriter::writeRecordUnsafe(const RecordType& token, const UnresolvedNativeFrame& record)
{
    return writeSimpleType(token) && writeSimpleType(record.ip) && writeVarint(record.index);
}

}  // namespace memray::tracking_api
