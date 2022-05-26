#include <chrono>
#include <fcntl.h>
#include <stdexcept>

#include "record_writer.h"

namespace memray::tracking_api {

using namespace std::chrono;

static PythonAllocatorType
getPythonAllocator()
{
#if PY_VERSION_HEX >= 0x03080000
    const char* name = _PyMem_GetCurrentAllocatorName();
#elif PY_VERSION_HEX >= 0x03070000
    const char* name = _PyMem_GetAllocatorsName();
#else
    const char* name = "";
#endif
    std::string allocator_name = name != NULL ? name : "";
    if (allocator_name == "pymalloc") {
        return PythonAllocatorType::PYTHONALLOCATOR_PYMALLOC;
    }
    if (allocator_name == "pymalloc_debug") {
        return PythonAllocatorType::PYTHONALLOCATOR_PYMALLOC_DEBUG;
    }
    if (allocator_name == "malloc") {
        return PythonAllocatorType::PYTHONALLOCATOR_MALLOC;
    }
    return PythonAllocatorType::PYTHONALLOCATOR_OTHER;
}

RecordWriter::RecordWriter(
        std::unique_ptr<memray::io::Sink> sink,
        const std::string& command_line,
        bool native_traces)
: d_sink(std::move(sink))
, d_stats{duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count()}
{
    d_header = HeaderRecord{
            "",
            d_version,
            native_traces,
            duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count(),
            command_line,
            ::getpid(),
            getPythonAllocator()};
    strncpy(d_header.magic, MAGIC, sizeof(d_header.magic));
}

RecordWriter::~RecordWriter()
{
    RecordTypeAndFlags token{RecordType::OTHER, static_cast<unsigned char>(OtherRecordType::STATS)};
    d_stats.time = duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
    if (writeSimpleType(token)) {
        writeSimpleType(d_stats);
    }
}

bool
RecordWriter::writeHeader(bool seek_to_start)
{
    std::lock_guard<std::mutex> lock(d_mutex);
    if (seek_to_start) {
        return true;
    }

    if (!writeSimpleType(d_header.magic) or !writeSimpleType(d_header.version)
        or !writeSimpleType(d_header.native_traces) or !writeSimpleType(d_header.start_time)
        or !writeString(d_header.command_line.c_str()) or !writeSimpleType(d_header.pid)
        or !writeSimpleType(d_header.python_allocator))
    {
        return false;
    }
    return true;
}

std::unique_lock<std::mutex>
RecordWriter::acquireLock()
{
    return std::unique_lock<std::mutex>(d_mutex);
}

std::unique_ptr<RecordWriter>
RecordWriter::cloneInChildProcess()
{
    std::unique_ptr<io::Sink> new_sink = d_sink->cloneInChildProcess();
    if (!new_sink) {
        return {};
    }
    return std::make_unique<RecordWriter>(
            std::move(new_sink),
            d_header.command_line,
            d_header.native_traces);
}

}  // namespace memray::tracking_api
