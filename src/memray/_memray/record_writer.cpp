#include "record_writer.h"

#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <stdexcept>

#include "records.h"

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
    std::string allocator_name = name != nullptr ? name : "";
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

RecordWriter::RecordWriter(std::unique_ptr<memray::io::Sink> sink)
: d_sink(std::move(sink))
{
}

class StreamingRecordWriter : public RecordWriter
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

    bool writeRecord(const MemoryRecord& record) override;
    bool writeRecord(const pyrawframe_map_val_t& item) override;
    bool writeRecord(const UnresolvedNativeFrame& record) override;

    bool writeMappings(const std::vector<ImageSegments>& mappings) override;

    bool writeThreadSpecificRecord(thread_id_t tid, const FramePop& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const FramePush& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const AllocationRecord& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const NativeAllocationRecord& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const ThreadRecord& record) override;

    bool writeHeader(bool seek_to_start) override;
    bool writeTrailer() override;

    void setMainTidAndSkippedFrames(thread_id_t main_tid, size_t skipped_frames_on_main_tid) override;
    std::unique_ptr<RecordWriter> cloneInChildProcess() override;

  private:
    bool maybeWriteContextSwitchRecordUnsafe(thread_id_t tid);

    // Data members
    int d_version{CURRENT_HEADER_VERSION};
    HeaderRecord d_header{};
    TrackerStats d_stats{};
    DeltaEncodedFields d_last;
};

std::unique_ptr<RecordWriter>
createRecordWriter(
        std::unique_ptr<memray::io::Sink> sink,
        const std::string& command_line,
        bool native_traces,
        FileFormat file_format)
{
    if (file_format == FileFormat::ALL_ALLOCATIONS) {
        return std::make_unique<StreamingRecordWriter>(std::move(sink), command_line, native_traces);
    } else {
        throw std::runtime_error("Invalid file format enumerator");
    }
}

StreamingRecordWriter::StreamingRecordWriter(
        std::unique_ptr<memray::io::Sink> sink,
        const std::string& command_line,
        bool native_traces)
: RecordWriter(std::move(sink))
, d_stats({0, 0, duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count()})
{
    d_header = HeaderRecord{
            "",
            d_version,
            native_traces,
            FileFormat::ALL_ALLOCATIONS,
            d_stats,
            command_line,
            ::getpid(),
            0,
            0,
            getPythonAllocator()};
    strncpy(d_header.magic, MAGIC, sizeof(d_header.magic));
}

void
StreamingRecordWriter::setMainTidAndSkippedFrames(
        thread_id_t main_tid,
        size_t skipped_frames_on_main_tid)
{
    d_header.main_tid = main_tid;
    d_header.skipped_frames_on_main_tid = skipped_frames_on_main_tid;
}

bool
StreamingRecordWriter::writeRecord(const MemoryRecord& record)
{
    RecordTypeAndFlags token{RecordType::MEMORY_RECORD, 0};
    return writeSimpleType(token) && writeVarint(record.rss)
           && writeVarint(record.ms_since_epoch - d_stats.start_time) && d_sink->flush();
}

bool
StreamingRecordWriter::writeRecord(const pyrawframe_map_val_t& item)
{
    d_stats.n_frames += 1;
    RecordTypeAndFlags token{RecordType::FRAME_INDEX, !item.second.is_entry_frame};
    return writeSimpleType(token) && writeIntegralDelta(&d_last.python_frame_id, item.first)
           && writeString(item.second.function_name) && writeString(item.second.filename)
           && writeIntegralDelta(&d_last.python_line_number, item.second.lineno);
}

bool
StreamingRecordWriter::writeRecord(const UnresolvedNativeFrame& record)
{
    return writeSimpleType(RecordTypeAndFlags{RecordType::NATIVE_TRACE_INDEX, 0})
           && writeIntegralDelta(&d_last.instruction_pointer, record.ip)
           && writeIntegralDelta(&d_last.native_frame_id, record.index);
}

bool
StreamingRecordWriter::writeMappings(const std::vector<ImageSegments>& mappings)
{
    return writeMappingsCommon(mappings);
}

bool
RecordWriter::writeMappingsCommon(const std::vector<ImageSegments>& mappings)
{
    RecordTypeAndFlags start_token{RecordType::MEMORY_MAP_START, 0};
    if (!writeSimpleType(start_token)) {
        return false;
    }

    for (const auto& image : mappings) {
        RecordTypeAndFlags segment_header_token{RecordType::SEGMENT_HEADER, 0};
        if (!writeSimpleType(segment_header_token) || !writeString(image.filename.c_str())
            || !writeVarint(image.segments.size()) || !writeSimpleType(image.addr))
        {
            return false;
        }

        RecordTypeAndFlags segment_token{RecordType::SEGMENT, 0};

        for (const auto& segment : image.segments) {
            if (!writeSimpleType(segment_token) || !writeSimpleType(segment.vaddr)
                || !writeVarint(segment.memsz)) {
                return false;
            }
        }
    }

    return true;
}

bool
StreamingRecordWriter::maybeWriteContextSwitchRecordUnsafe(thread_id_t tid)
{
    if (d_last.thread_id == tid) {
        return true;  // nothing to do.
    }
    d_last.thread_id = tid;

    RecordTypeAndFlags token{RecordType::CONTEXT_SWITCH, 0};
    ContextSwitch record{tid};
    return writeSimpleType(token) && writeSimpleType(record);
}

bool
StreamingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const FramePop& record)
{
    if (!maybeWriteContextSwitchRecordUnsafe(tid)) {
        return false;
    }

    size_t count = record.count;
    while (count) {
        uint8_t to_pop = (count > 16 ? 16 : count);
        count -= to_pop;

        to_pop -= 1;  // i.e. 0 means pop 1 frame, 15 means pop 16 frames
        RecordTypeAndFlags token{RecordType::FRAME_POP, to_pop};
        assert(token.flags == to_pop);
        if (!writeSimpleType(token)) {
            return false;
        }
    }

    return true;
}

bool
StreamingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const FramePush& record)
{
    if (!maybeWriteContextSwitchRecordUnsafe(tid)) {
        return false;
    }

    RecordTypeAndFlags token{RecordType::FRAME_PUSH, 0};
    return writeSimpleType(token) && writeIntegralDelta(&d_last.python_frame_id, record.frame_id);
}

bool
StreamingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const AllocationRecord& record)
{
    if (!maybeWriteContextSwitchRecordUnsafe(tid)) {
        return false;
    }

    d_stats.n_allocations += 1;
    RecordTypeAndFlags token{RecordType::ALLOCATION, static_cast<unsigned char>(record.allocator)};
    return writeSimpleType(token) && writeIntegralDelta(&d_last.data_pointer, record.address)
           && (hooks::allocatorKind(record.allocator) == hooks::AllocatorKind::SIMPLE_DEALLOCATOR
               || writeVarint(record.size));
}

bool
StreamingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const NativeAllocationRecord& record)
{
    if (!maybeWriteContextSwitchRecordUnsafe(tid)) {
        return false;
    }

    d_stats.n_allocations += 1;
    RecordTypeAndFlags token{
            RecordType::ALLOCATION_WITH_NATIVE,
            static_cast<unsigned char>(record.allocator)};
    return writeSimpleType(token) && writeIntegralDelta(&d_last.data_pointer, record.address)
           && writeVarint(record.size)
           && writeIntegralDelta(&d_last.native_frame_id, record.native_frame_id);
}

bool
StreamingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const ThreadRecord& record)
{
    if (!maybeWriteContextSwitchRecordUnsafe(tid)) {
        return false;
    }

    RecordTypeAndFlags token{RecordType::THREAD_RECORD, 0};
    return writeSimpleType(token) && writeString(record.name);
}

bool
StreamingRecordWriter::writeHeader(bool seek_to_start)
{
    if (seek_to_start) {
        // If we can't seek to the beginning to the stream (e.g. dealing with a socket), just give
        // up.
        if (!d_sink->seek(0, SEEK_SET)) {
            return false;
        }
    }

    d_stats.end_time = duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
    d_header.stats = d_stats;
    return writeHeaderCommon(d_header);
}

bool
RecordWriter::writeHeaderCommon(const HeaderRecord& header)
{
    if (!writeSimpleType(header.magic) or !writeSimpleType(header.version)
        or !writeSimpleType(header.native_traces) or !writeSimpleType(header.file_format)
        or !writeSimpleType(header.stats) or !writeString(header.command_line.c_str())
        or !writeSimpleType(header.pid) or !writeSimpleType(header.main_tid)
        or !writeSimpleType(header.skipped_frames_on_main_tid)
        or !writeSimpleType(header.python_allocator))
    {
        return false;
    }
    return true;
}

bool
StreamingRecordWriter::writeTrailer()
{
    // The FileSource will ignore trailing 0x00 bytes. This non-zero trailer
    // marks the boundary between bytes we wrote and padding bytes.
    RecordTypeAndFlags token{RecordType::OTHER, int(OtherRecordType::TRAILER)};
    return writeSimpleType(token);
}

std::unique_ptr<RecordWriter>
StreamingRecordWriter::cloneInChildProcess()
{
    std::unique_ptr<io::Sink> new_sink = d_sink->cloneInChildProcess();
    if (!new_sink) {
        return {};
    }
    return std::make_unique<StreamingRecordWriter>(
            std::move(new_sink),
            d_header.command_line,
            d_header.native_traces);
}

}  // namespace memray::tracking_api
