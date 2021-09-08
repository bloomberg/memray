#include <chrono>
#include <fcntl.h>
#include <stdexcept>

#include "exceptions.h"
#include "record_writer.h"

namespace pensieve::tracking_api {

using namespace std::chrono;

RecordWriter::RecordWriter(
        std::unique_ptr<pensieve::io::Sink> sink,
        const std::string& command_line,
        bool native_traces)
: d_buffer(new char[BUFFER_CAPACITY]{0})
, d_sink(std::move(sink))
, d_command_line(command_line)
, d_native_traces(native_traces)
, d_stats({0, 0, duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count()})
{
    d_header = HeaderRecord{"", d_version, d_native_traces, d_stats, d_command_line};
    strncpy(d_header.magic, MAGIC, sizeof(MAGIC));
}

RecordWriter::~RecordWriter()
{
    d_sink->close();
}

bool
RecordWriter::flush()
{
    std::lock_guard<std::mutex> lock(d_mutex);
    return _flush();
}

bool
RecordWriter::_flush()
{
    if (!d_used_bytes) {
        return true;
    }

    if (!d_sink->writeAll(d_buffer.get(), d_used_bytes)) {
        return false;
    }

    d_used_bytes = 0;

    return true;
}

bool
RecordWriter::writeHeader(bool seek_to_start)
{
    std::lock_guard<std::mutex> lock(d_mutex);
    if (!_flush()) {
        return false;
    }

    if (seek_to_start) {
        // If we can't seek to the beginning to the stream (e.g. dealing with a socket), just give
        // up.
        if (!d_sink->seek(0, SEEK_SET)) {
            return false;
        }
    }

    d_stats.end_time = duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
    d_header.stats = d_stats;
    try {
        writeSimpleType(d_header.magic);
        writeSimpleType(d_header.version);
        writeSimpleType(d_header.native_traces);
        writeSimpleType(d_header.stats);
        writeString(d_header.command_line.c_str());
    } catch (const pensieve::exception::IoError&) {
        return false;
    }

    return true;
}

std::unique_lock<std::mutex>
RecordWriter::acquireLock()
{
    return std::unique_lock<std::mutex>(d_mutex);
}

}  // namespace pensieve::tracking_api
