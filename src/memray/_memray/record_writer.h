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
    bool inline writeSimpleType(const T& item);
    bool inline writeString(const char* the_string);
    bool inline writeVarint(size_t val);
    template<typename T>
    bool inline writeRecord(const T& item);
    template<typename T>
    bool inline writeThreadSpecificRecord(thread_id_t tid, const T& item);
    bool inline writeRecordUnsafe(const FramePop& record);
    bool inline writeRecordUnsafe(const FramePush& record);
    bool inline writeRecordUnsafe(const MemoryRecord& record);
    bool inline writeRecordUnsafe(const ContextSwitch& record);
    bool inline writeRecordUnsafe(const Segment& record);
    bool inline writeRecordUnsafe(const AllocationRecord& record);
    bool inline writeRecordUnsafe(const NativeAllocationRecord& record);
    bool inline writeRecordUnsafe(const pyrawframe_map_val_t& item);
    bool inline writeRecordUnsafe(const SegmentHeader& item);
    bool inline writeRecordUnsafe(const ThreadRecord& record);
    bool inline writeRecordUnsafe(const UnresolvedNativeFrame& record);
    bool inline writeRecordUnsafe(const MemoryMapStart&);
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
bool inline RecordWriter::writeSimpleType(const T& item)
{
    static_assert(
            std::is_trivially_copyable<T>::value,
            "writeSimpleType called on non trivially copyable type");

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
bool inline RecordWriter::writeRecord(const T& item)
{
    std::lock_guard<std::mutex> lock(d_mutex);
    return writeRecordUnsafe(item);
}

template<typename T>
bool inline RecordWriter::writeThreadSpecificRecord(thread_id_t tid, const T& item)
{
    std::lock_guard<std::mutex> lock(d_mutex);
    if (d_lastTid != tid) {
        d_lastTid = tid;
        if (!writeRecordUnsafe(ContextSwitch{tid})) {
            return false;
        }
    }
    return writeRecordUnsafe(item);
}

bool inline RecordWriter::writeRecordUnsafe(const FramePop& record)
{
    size_t count = record.count;
    while (count) {
        uint8_t to_pop = (count > 64 ? 64 : count);
        count -= to_pop;

        to_pop -= 1;  // i.e. 0 means pop 1 frame, 63 means pop 64 frames
        RecordTypeAndFlags token{RecordType::FRAME_POP, to_pop};
        if (!writeSimpleType(token)) {
            return false;
        }
    }

    return true;
}

bool inline RecordWriter::writeRecordUnsafe(const FramePush& record)
{
    RecordTypeAndFlags token{RecordType::FRAME_PUSH, 0};
    return writeSimpleType(token) && writeVarint(record.frame_id);
}

bool inline RecordWriter::writeRecordUnsafe(const MemoryRecord& record)
{
    RecordTypeAndFlags token{RecordType::MEMORY_RECORD, 0};
    return writeSimpleType(token) && writeVarint(record.rss)
           && writeVarint(record.ms_since_epoch - d_stats.start_time);
}

bool inline RecordWriter::writeRecordUnsafe(const ContextSwitch& record)
{
    RecordTypeAndFlags token{RecordType::CONTEXT_SWITCH, 0};
    return writeSimpleType(token) && writeSimpleType(record);
}

bool inline RecordWriter::writeRecordUnsafe(const Segment& record)
{
    RecordTypeAndFlags token{RecordType::SEGMENT, 0};
    return writeSimpleType(token) && writeSimpleType(record.vaddr) && writeVarint(record.memsz);
}

bool inline RecordWriter::writeRecordUnsafe(const AllocationRecord& record)
{
    d_stats.n_allocations += 1;
    RecordTypeAndFlags token{RecordType::ALLOCATION, static_cast<unsigned char>(record.allocator)};
    return writeSimpleType(token) && writeSimpleType(record.address)
           && (hooks::allocatorKind(record.allocator) == hooks::AllocatorKind::SIMPLE_DEALLOCATOR
               || writeVarint(record.size));
}

bool inline RecordWriter::writeRecordUnsafe(const NativeAllocationRecord& record)
{
    d_stats.n_allocations += 1;
    RecordTypeAndFlags token{
            RecordType::ALLOCATION_WITH_NATIVE,
            static_cast<unsigned char>(record.allocator)};
    return writeSimpleType(token) && writeSimpleType(record.address) && writeVarint(record.size)
           && writeVarint(record.native_frame_id);
}

bool inline RecordWriter::writeRecordUnsafe(const pyrawframe_map_val_t& item)
{
    d_stats.n_frames += 1;
    RecordTypeAndFlags token{RecordType::FRAME_INDEX, 0};
    return writeSimpleType(token) && writeSimpleType(item.first)
           && writeString(item.second.function_name) && writeString(item.second.filename)
           && writeSimpleType(item.second.lineno);
}

bool inline RecordWriter::writeRecordUnsafe(const SegmentHeader& item)
{
    RecordTypeAndFlags token{RecordType::SEGMENT_HEADER, 0};
    return writeSimpleType(token) && writeString(item.filename) && writeSimpleType(item.num_segments)
           && writeSimpleType(item.addr);
}

bool inline RecordWriter::writeRecordUnsafe(const ThreadRecord& record)
{
    RecordTypeAndFlags token{RecordType::THREAD_RECORD, 0};
    return writeSimpleType(token) && writeString(record.name);
}

bool inline RecordWriter::writeRecordUnsafe(const UnresolvedNativeFrame& record)
{
    return writeSimpleType(RecordTypeAndFlags{RecordType::NATIVE_TRACE_INDEX, 0})
           && writeSimpleType(record.ip) && writeVarint(record.index);
}

bool inline RecordWriter::writeRecordUnsafe(const MemoryMapStart&)
{
    RecordTypeAndFlags token{RecordType::MEMORY_MAP_START, 0};
    return writeSimpleType(token);
}

}  // namespace memray::tracking_api
