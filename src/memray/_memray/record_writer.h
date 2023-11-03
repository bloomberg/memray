#pragma once

#include <limits>
#include <string>
#include <type_traits>
#include <unistd.h>

#include "sink.h"

namespace memray::tracking_api {

class RecordWriter
{
  public:
    virtual ~RecordWriter() = default;

    RecordWriter(RecordWriter& other) = delete;
    RecordWriter(RecordWriter&& other) = delete;
    void operator=(const RecordWriter&) = delete;
    void operator=(RecordWriter&&) = delete;

    virtual bool writeRecord(const MemoryRecord& record) = 0;
    virtual bool writeRecord(const pyrawframe_map_val_t& item) = 0;
    virtual bool writeRecord(const UnresolvedNativeFrame& record) = 0;

    virtual bool writeMappings(const std::vector<ImageSegments>& mappings) = 0;

    virtual bool writeThreadSpecificRecord(thread_id_t tid, const FramePop& record) = 0;
    virtual bool writeThreadSpecificRecord(thread_id_t tid, const FramePush& record) = 0;
    virtual bool writeThreadSpecificRecord(thread_id_t tid, const AllocationRecord& record) = 0;
    virtual bool writeThreadSpecificRecord(thread_id_t tid, const NativeAllocationRecord& record) = 0;
    virtual bool writeThreadSpecificRecord(thread_id_t tid, const ThreadRecord& record) = 0;

    virtual bool writeHeader(bool seek_to_start) = 0;
    virtual bool writeTrailer() = 0;

    virtual void setMainTidAndSkippedFrames(thread_id_t main_tid, size_t skipped_frames_on_main_tid) = 0;
    virtual std::unique_ptr<RecordWriter> cloneInChildProcess() = 0;

  protected:
    // Expose the sink for use by the following helper functions.
    explicit RecordWriter(std::unique_ptr<memray::io::Sink> sink);
    std::unique_ptr<memray::io::Sink> d_sink;

    // Helper functions for common code needed by both subclasses.
    bool writeHeaderCommon(const HeaderRecord&);
    bool writeMappingsCommon(const std::vector<ImageSegments>&);

    template<typename T>
    bool inline writeSimpleType(const T& item);

    bool inline writeString(const char* the_string);
    bool inline writeVarint(size_t val);
    bool inline writeSignedVarint(ssize_t val);

    template<typename T>
    bool inline writeIntegralDelta(T* prev, T new_val);
};

std::unique_ptr<RecordWriter>
createRecordWriter(
        std::unique_ptr<memray::io::Sink> sink,
        const std::string& command_line,
        bool native_traces,
        FileFormat file_format,
        bool trace_python_allocators);

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

bool inline RecordWriter::writeSignedVarint(ssize_t val)
{
    // protobuf style "zig-zag" encoding
    // https://developers.google.com/protocol-buffers/docs/encoding#signed-ints
    // This encodes -64 through 63 in 1 byte, -8192 through 8191 in 2 bytes, etc
    size_t zigzag_val = (static_cast<size_t>(val) << 1)
                        ^ static_cast<size_t>(val >> std::numeric_limits<ssize_t>::digits);
    return writeVarint(zigzag_val);
}

template<typename T>
bool inline RecordWriter::writeIntegralDelta(T* prev, T new_val)
{
    ssize_t delta = new_val - *prev;
    *prev = new_val;
    return writeSignedVarint(delta);
}

}  // namespace memray::tracking_api
