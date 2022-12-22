#pragma once

#include <cerrno>
#include <climits>
#include <cstring>
#include <memory>
#include <string>
#include <type_traits>
#include <unistd.h>

#include "records.h"
#include "sink.h"

namespace memray::tracking_api {

class StreamingRecordWriter
{
  public:
    explicit StreamingRecordWriter(
            std::unique_ptr<memray::io::Sink> sink,
            const std::string& command_line,
            bool native_traces);

    StreamingRecordWriter(StreamingRecordWriter& other) = delete;
    StreamingRecordWriter(StreamingRecordWriter&& other) = delete;
    void operator=(const StreamingRecordWriter&) = delete;
    void operator=(StreamingRecordWriter&&) = delete;

    bool writeRecord(const MemoryRecord& record);
    bool writeRecord(const pyrawframe_map_val_t& item);
    bool writeRecord(const UnresolvedNativeFrame& record);

    bool writeMappings(const std::vector<ImageSegments>& mappings);

    bool writeThreadSpecificRecord(thread_id_t tid, const FramePop& record);
    bool writeThreadSpecificRecord(thread_id_t tid, const FramePush& record);
    bool writeThreadSpecificRecord(thread_id_t tid, const AllocationRecord& record);
    bool writeThreadSpecificRecord(thread_id_t tid, const NativeAllocationRecord& record);
    bool writeThreadSpecificRecord(thread_id_t tid, const ThreadRecord& record);

    bool writeHeader(bool seek_to_start);
    bool writeTrailer();

    void setMainTidAndSkippedFrames(thread_id_t main_tid, size_t skipped_frames_on_main_tid);
    std::unique_ptr<StreamingRecordWriter> cloneInChildProcess();

  private:
    bool maybeWriteContextSwitchRecordUnsafe(thread_id_t tid);

    template<typename T>
    bool inline writeSimpleType(const T& item);
    bool inline writeString(const char* the_string);
    bool inline writeVarint(size_t val);
    bool inline writeSignedVarint(ssize_t val);
    template<typename T>
    bool inline writeIntegralDelta(T* prev, T new_val);

    // Data members
    int d_version{CURRENT_HEADER_VERSION};
    std::unique_ptr<memray::io::Sink> d_sink;
    HeaderRecord d_header{};
    TrackerStats d_stats{};
    DeltaEncodedFields d_last;
};

using RecordWriter = StreamingRecordWriter;

template<typename T>
bool inline StreamingRecordWriter::writeSimpleType(const T& item)
{
    static_assert(
            std::is_trivially_copyable<T>::value,
            "writeSimpleType called on non trivially copyable type");

    return d_sink->writeAll(reinterpret_cast<const char*>(&item), sizeof(item));
};

bool inline StreamingRecordWriter::writeString(const char* the_string)
{
    return d_sink->writeAll(the_string, strlen(the_string) + 1);
}

bool inline StreamingRecordWriter::writeVarint(size_t rest)
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

bool inline StreamingRecordWriter::writeSignedVarint(ssize_t val)
{
    // protobuf style "zig-zag" encoding
    // https://developers.google.com/protocol-buffers/docs/encoding#signed-ints
    // This encodes -64 through 63 in 1 byte, -8192 through 8191 in 2 bytes, etc
    size_t zigzag_val = (static_cast<size_t>(val) << 1)
                        ^ static_cast<size_t>(val >> std::numeric_limits<ssize_t>::digits);
    return writeVarint(zigzag_val);
}

template<typename T>
bool inline StreamingRecordWriter::writeIntegralDelta(T* prev, T new_val)
{
    ssize_t delta = new_val - *prev;
    *prev = new_val;
    return writeSignedVarint(delta);
}

}  // namespace memray::tracking_api
