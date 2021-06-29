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

namespace pensieve::tracking_api {

class RecordWriter
{
  public:
    explicit RecordWriter(
            const std::string& file_name,
            const std::string& command_line,
            bool native_traces);
    ~RecordWriter();

    RecordWriter(RecordWriter& other) = delete;
    RecordWriter(RecordWriter&& other) = delete;
    void operator=(const RecordWriter&) = delete;
    void operator=(RecordWriter&&) = delete;

    template<typename T>
    bool inline writeSimpleType(T&& item) noexcept;
    bool inline writeString(const char* the_string) noexcept;
    template<typename T>
    bool inline writeRecord(const RecordType& token, const T& item) noexcept;
    bool writeHeader() noexcept;

    bool flush() noexcept;

  private:
    // Constants
    static const size_t BUFFER_CAPACITY = PIPE_BUF;

    // Data members
    int fd{-1};
    int d_version{CURRENT_HEADER_VERSION};
    unsigned d_used_bytes{0};
    std::unique_ptr<char[]> d_buffer{nullptr};
    std::mutex d_mutex;
    HeaderRecord d_header{};
    const std::string& d_command_line;
    bool d_native_traces;
    TrackerStats d_stats{};

    // Methods
    bool inline writeAll(const char* buffer, size_t length);
    inline size_t availableSpace() const noexcept;
    inline char* bufferNeedle() const noexcept;
    bool _flush() noexcept;
};

inline size_t
RecordWriter::availableSpace() const noexcept
{
    return BUFFER_CAPACITY - d_used_bytes;
}

inline char*
RecordWriter::bufferNeedle() const noexcept
{
    return d_buffer.get() + d_used_bytes;
}

bool inline RecordWriter::writeAll(const char* data, size_t length)
{
    while (length) {
        int ret = write(fd, data, length);
        if (ret < 0 && errno != EINTR) {
            return false;
        } else if (ret >= 0) {
            data += ret;
            length -= ret;
        }
    }
    return true;
}

template<typename T>
bool inline RecordWriter::writeSimpleType(T&& item) noexcept
{
    return writeAll(reinterpret_cast<const char*>(&item), sizeof(item));
};

bool inline RecordWriter::writeString(const char* the_string) noexcept
{
    return writeAll(the_string, strlen(the_string) + 1);
}

template<typename T>
bool inline RecordWriter::writeRecord(const RecordType& token, const T& item) noexcept
{
    std::lock_guard<std::mutex> lock(d_mutex);
    constexpr const size_t total = sizeof(RecordType) + sizeof(T);
    static_assert(
            std::is_trivially_copyable<T>::value,
            "Called writeRecord on binary records which cannot be trivially copied");
    static_assert(total < BUFFER_CAPACITY, "cannot write lineno larger than d_buffer capacity");

    if (total > availableSpace() && !_flush()) {
        return false;
    }
    if (token == RecordType::ALLOCATION) {
        d_stats.n_allocations += 1;
    }
    ::memcpy(bufferNeedle(), reinterpret_cast<const void*>(&token), sizeof(RecordType));
    d_used_bytes += sizeof(RecordType);
    ::memcpy(bufferNeedle(), reinterpret_cast<const void*>(&item), sizeof(T));
    d_used_bytes += sizeof(T);
    return true;
}

template<>
bool inline RecordWriter::writeRecord(const RecordType& token, const pyframe_map_val_t& item) noexcept
{
    std::lock_guard<std::mutex> lock(d_mutex);
    if (!_flush()) {
        return false;
    }

    d_stats.n_frames += 1;
    return writeSimpleType(token) && writeSimpleType(item.first)
           && writeString(item.second.function_name.c_str()) && writeString(item.second.filename.c_str())
           && writeSimpleType(item.second.parent_lineno);
}

template<>
bool inline RecordWriter::writeRecord(const RecordType& token, const SegmentHeader& item) noexcept
{
    std::lock_guard<std::mutex> lock(d_mutex);
    if (!_flush()) {
        return false;
    }

    return writeSimpleType(token) && writeString(item.filename) && writeSimpleType(item.num_segments)
           && writeSimpleType(item.addr);
}

}  // namespace pensieve::tracking_api
