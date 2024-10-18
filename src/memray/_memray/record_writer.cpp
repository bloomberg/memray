#include "record_writer.h"

#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <stdexcept>

#include "frame_tree.h"
#include "records.h"
#include "snapshot.h"

#if PY_VERSION_HEX >= 0x030D0000
// This function still exists in 3.13 but Python.h no longer has its prototype.
extern "C" const char*
_PyMem_GetCurrentAllocatorName();
#endif

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
    if (allocator_name == "mimalloc") {
        return PythonAllocatorType::PYTHONALLOCATOR_MIMALLOC;
    }
    if (allocator_name == "mimalloc_debug") {
        return PythonAllocatorType::PYTHONALLOCATOR_MIMALLOC_DEBUG;
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
            bool native_traces,
            bool trace_python_allocators,
            bool track_object_lifetimes);

    StreamingRecordWriter(StreamingRecordWriter& other) = delete;
    StreamingRecordWriter(StreamingRecordWriter&& other) = delete;
    void operator=(const StreamingRecordWriter&) = delete;
    void operator=(StreamingRecordWriter&&) = delete;

    bool writeRecord(const MemoryRecord& record) override;
    bool writeRecord(const pycode_map_val_t& item) override;
    bool writeRecord(const UnresolvedNativeFrame& record) override;

    bool writeMappings(const std::vector<ImageSegments>& mappings) override;

    bool writeThreadSpecificRecord(thread_id_t tid, const FramePop& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const FramePush& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const AllocationRecord& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const ThreadRecord& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const ObjectRecord& record) override;

    bool writeHeader(bool seek_to_start) override;
    bool writeTrailer() override;

    void setMainTidAndSkippedFrames(thread_id_t main_tid, size_t skipped_frames_on_main_tid) override;
    std::unique_ptr<RecordWriter> cloneInChildProcess() override;

  private:
    bool maybeWriteContextSwitchRecordUnsafe(thread_id_t tid);
    int pointerCacheIndex(uintptr_t ptr);

    // Data members
    int d_version{CURRENT_HEADER_VERSION};
    HeaderRecord d_header{};
    TrackerStats d_stats{};
    // LRU Pointer Cache System
    // ========================
    // Recent allocation addresses are cached to avoid repeating pointers.
    // - Cache holds 15 most recent unique addresses (indices 0-14)
    // - Index 0 = most recently added, 14 = least recently added
    // - On miss: new address inserted at index 0, others shift right, index 14 drops
    //
    // Wire format uses 4 bits (pppp):
    //   0x0-0xE (0-14): Cache hit - reuse address at this index
    //   0xF (15):       Cache miss - read/write full address, update cache
    //
    // Compression example:
    //   malloc() returns 0x7fff8000 five times, free() called five times
    //   Traditional: 5 * 8 bytes (addresses) = 40 bytes
    //   With cache:  8 bytes (first addr) + 5 * 0 bytes (cache hits) = 8 bytes
    //
    // CRITICAL: Reader and writer caches must stay synchronized by processing
    //           records in identical order with identical LRU updates.
    std::array<uintptr_t, 15> d_recent_addresses{};
    DeltaEncodedFields d_last;
};

class AggregatingRecordWriter : public RecordWriter
{
  public:
    explicit AggregatingRecordWriter(
            std::unique_ptr<memray::io::Sink> sink,
            const std::string& command_line,
            bool native_traces,
            bool trace_python_allocators,
            bool track_object_lifetimes);

    AggregatingRecordWriter(StreamingRecordWriter& other) = delete;
    AggregatingRecordWriter(StreamingRecordWriter&& other) = delete;
    void operator=(const AggregatingRecordWriter&) = delete;
    void operator=(AggregatingRecordWriter&&) = delete;

    bool writeRecord(const MemoryRecord& record) override;
    bool writeRecord(const pycode_map_val_t& item) override;
    bool writeRecord(const UnresolvedNativeFrame& record) override;

    bool writeMappings(const std::vector<ImageSegments>& mappings) override;

    bool writeThreadSpecificRecord(thread_id_t tid, const FramePop& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const FramePush& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const AllocationRecord& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const ThreadRecord& record) override;
    bool writeThreadSpecificRecord(thread_id_t tid, const ObjectRecord& record) override;

    bool writeHeader(bool seek_to_start) override;
    bool writeTrailer() override;

    void setMainTidAndSkippedFrames(thread_id_t main_tid, size_t skipped_frames_on_main_tid) override;
    std::unique_ptr<RecordWriter> cloneInChildProcess() override;

  private:
    // Aliases
    using python_stack_ids_t = std::vector<FrameTree::index_t>;
    using python_stack_ids_by_tid = std::unordered_map<thread_id_t, python_stack_ids_t>;

    // Data members
    HeaderRecord d_header;
    TrackerStats d_stats;
    Registry<Frame> d_python_frame_registry;
    std::unordered_map<code_object_id_t, CodeObjectInfo> d_code_objects_by_id;
    std::vector<UnresolvedNativeFrame> d_native_frames{};
    std::vector<std::vector<ImageSegments>> d_mappings_by_generation{};
    std::vector<MemorySnapshot> d_memory_snapshots;
    std::unordered_map<thread_id_t, std::string> d_thread_name_by_tid;
    FrameTree d_python_frame_tree;
    python_stack_ids_by_tid d_python_stack_ids_by_thread;
    std::unordered_map<uintptr_t, frame_id_t> d_surviving_objects;
    DeltaEncodedFields d_last;
    api::HighWaterMarkAggregator d_high_water_mark_aggregator;
};

std::unique_ptr<RecordWriter>
createRecordWriter(
        std::unique_ptr<memray::io::Sink> sink,
        const std::string& command_line,
        bool native_traces,
        FileFormat file_format,
        bool trace_python_allocators,
        bool track_object_lifetimes)
{
    switch (file_format) {
        case FileFormat::ALL_ALLOCATIONS:
            return std::make_unique<StreamingRecordWriter>(
                    std::move(sink),
                    command_line,
                    native_traces,
                    trace_python_allocators,
                    track_object_lifetimes);
        case FileFormat::AGGREGATED_ALLOCATIONS:
            return std::make_unique<AggregatingRecordWriter>(
                    std::move(sink),
                    command_line,
                    native_traces,
                    trace_python_allocators,
                    track_object_lifetimes);
        default:
            throw std::runtime_error("Invalid file format enumerator");
    }
}

StreamingRecordWriter::StreamingRecordWriter(
        std::unique_ptr<memray::io::Sink> sink,
        const std::string& command_line,
        bool native_traces,
        bool trace_python_allocators,
        bool track_object_lifetimes)
: RecordWriter(std::move(sink))
, d_stats({0, 0, duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count()})
{
    d_header = HeaderRecord{
            "",
            d_version,
            PY_VERSION_HEX,
            native_traces,
            FileFormat::ALL_ALLOCATIONS,
            d_stats,
            command_line,
            ::getpid(),
            0,
            0,
            getPythonAllocator(),
            trace_python_allocators,
            track_object_lifetimes};
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
    auto token = static_cast<unsigned char>(RecordType::MEMORY_RECORD);
    return writeSimpleType(token) && writeVarint(record.rss)
           && writeVarint(record.ms_since_epoch - d_stats.start_time) && d_sink->flush();
}

bool
StreamingRecordWriter::writeRecord(const pycode_map_val_t& item)
{
    auto token = static_cast<unsigned char>(RecordType::CODE_OBJECT);
    return writeSimpleType(token) && writeVarint(item.first)
           && writeString(item.second.function_name.c_str()) && writeString(item.second.filename.c_str())
           && writeIntegralDelta(&d_last.code_firstlineno, item.second.firstlineno)
           && writeVarint(item.second.linetable.size())
           && d_sink->writeAll(item.second.linetable.data(), item.second.linetable.size());
}

bool
StreamingRecordWriter::writeRecord(const UnresolvedNativeFrame& record)
{
    return writeSimpleType(static_cast<unsigned char>(RecordType::NATIVE_TRACE_INDEX))
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
    auto start_token = static_cast<unsigned char>(RecordType::MEMORY_MAP_START);
    if (!writeSimpleType(start_token)) {
        return false;
    }

    for (const auto& image : mappings) {
        auto segment_header_token = static_cast<unsigned char>(RecordType::SEGMENT_HEADER);
        if (!writeSimpleType(segment_header_token) || !writeString(image.filename.c_str())
            || !writeVarint(image.segments.size()) || !writeSimpleType(image.addr))
        {
            return false;
        }

        auto segment_token = static_cast<unsigned char>(RecordType::SEGMENT);

        for (const auto& segment : image.segments) {
            if (!writeSimpleType(segment_token) || !writeSimpleType(segment.vaddr)
                || !writeVarint(segment.memsz))
            {
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

    auto token = static_cast<unsigned char>(RecordType::CONTEXT_SWITCH);
    ContextSwitch record{tid};
    return writeSimpleType(token) && writeSimpleType(record);
}

int
StreamingRecordWriter::pointerCacheIndex(uintptr_t ptr)
{
    auto it = std::find(d_recent_addresses.begin(), d_recent_addresses.end(), ptr);
    if (it != d_recent_addresses.end()) {
        return static_cast<int>(std::distance(d_recent_addresses.begin(), it));
    }

    std::move(d_recent_addresses.begin(), d_recent_addresses.end() - 1, d_recent_addresses.begin() + 1);
    d_recent_addresses[0] = ptr;

    return -1;
}

bool
StreamingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const FramePop& record)
{
    if (!maybeWriteContextSwitchRecordUnsafe(tid)) {
        return false;
    }

    // FRAME_POP ENCODING: 0b0001nnnn, n+1 is number of frames to pop.
    // If there are more than 16 frames to pop, we emit multiple FRAME_POP records.
    size_t count = record.count;
    while (count) {
        uint8_t to_pop = (count > 16 ? 16 : count);
        count -= to_pop;

        to_pop -= 1;  // i.e. 0 means pop 1 frame, 15 means pop 16 frames
        auto token = static_cast<unsigned char>(RecordType::FRAME_POP);
        token |= to_pop;
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

    // FRAME_PUSH ENCODING: 0b01uuuuue, `u` are unused bits, `e` is is-entry-frame.
    // In the future we can use `u` to pack more information into the token,
    // like whether the code object id has been recently seen.
    // This is followed by the varint encoded code object id and instruction offset.
    auto token = static_cast<unsigned char>(RecordType::FRAME_PUSH);
    token |= record.frame.is_entry_frame;
    return writeSimpleType(token) && writeVarint(record.frame.code_object_id)
           && writeSignedVarint(record.frame.instruction_offset);
}

bool
StreamingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const AllocationRecord& record)
{
    if (!maybeWriteContextSwitchRecordUnsafe(tid)) {
        return false;
    }

    // ALLOCATION ENCODING: 0b1ppppaaa
    //
    // Bit layout of the first byte:
    // ┌─┬─────┬─────┐
    // │1│pppp │ aaa │
    // └─┴─────┴─────┘
    //  ↑   ↑     ↑
    //  │   │     └── Allocator ID (0-7):
    //  │   │           1-7: Common allocators (PYMALLOC_FREE, MALLOC, etc.)
    //  │   │             0: Uncommon allocator, full ID follows as separate byte
    //  │   └──────── Pointer cache index (0-15):
    //  │               0-14: Cache hit, reuse address at cache[index]
    //  │                 15: Cache miss, delta-encoded pointer follows
    //  └──────────── Record type marker (always 1 for ALLOCATION)
    //
    // Byte sequence after the type byte:
    // [pointer]     - Delta-encoded pointer >> 3 (only if pppp=15)
    // [allocator]   - Full allocator ID byte (only if aaa=0)
    // [native_id]   - Delta-encoded native_frame_id (only if native traces enabled
    //                 AND not a simple deallocator)
    // [size]        - Varint-encoded size (only if not a simple deallocator)
    //
    // Example sequences:
    // - Cached malloc(256):        [0b10011110] [size:256]
    //     (cache_idx=1, allocator=6)
    // - New pymalloc_free(ptr):    [0b11111001] [ptr_delta]
    //     (cache_miss, allocator=1, no size for deallocator)
    d_stats.n_allocations += 1;
    auto token = static_cast<unsigned char>(RecordType::ALLOCATION);

    auto allocator_id = static_cast<unsigned char>(record.allocator);
    if (allocator_id < 8) {
        token |= allocator_id;
    }

    int pointer_cache_index = pointerCacheIndex(record.address);
    token |= (pointer_cache_index & 0x0f) << 3;

    return writeSimpleType(token)
           && (pointer_cache_index != -1
               || writeIntegralDelta(&d_last.data_pointer, record.address >> 3))
           && (allocator_id < 8 || writeSimpleType(record.allocator))
           && (!d_header.native_traces
               || hooks::allocatorKind(record.allocator) == hooks::AllocatorKind::SIMPLE_DEALLOCATOR
               || writeIntegralDelta(&d_last.native_frame_id, record.native_frame_id))
           && (hooks::allocatorKind(record.allocator) == hooks::AllocatorKind::SIMPLE_DEALLOCATOR
               || writeVarint(record.size));
}

bool
StreamingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const ThreadRecord& record)
{
    if (!maybeWriteContextSwitchRecordUnsafe(tid)) {
        return false;
    }

    auto token = static_cast<unsigned char>(RecordType::THREAD_RECORD);
    return writeSimpleType(token) && writeString(record.name);
}

bool
StreamingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const ObjectRecord& record)
{
    if (!maybeWriteContextSwitchRecordUnsafe(tid)) {
        return false;
    }

    // OBJECT_RECORD ENCODING: 0b001ppppc
    // c: creation (1) or destruction (0)
    // p: 4 bit pointer cache exactly as in ALLOCATION
    // This byte is followed by the pointer on cache misses, exactly as in ALLOCATION.
    // For creations that is followed by the native frame id if native tracking is enabled.
    auto token = static_cast<unsigned char>(RecordType::OBJECT_RECORD);
    if (record.is_created) {
        token |= 1;
    }

    int pointer_cache_index = pointerCacheIndex(record.address);
    token |= (pointer_cache_index & 0x0f) << 1;

    return writeSimpleType(token)
           && (pointer_cache_index != -1
               || writeIntegralDelta(&d_last.data_pointer, record.address >> 3))
           && (!d_header.native_traces || !record.is_created
               || writeIntegralDelta(&d_last.native_frame_id, record.native_frame_id));
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
        or !writeSimpleType(header.python_version) or !writeSimpleType(header.native_traces)
        or !writeSimpleType(header.file_format) or !writeSimpleType(header.stats)
        or !writeString(header.command_line.c_str()) or !writeSimpleType(header.pid)
        or !writeSimpleType(header.main_tid) or !writeSimpleType(header.skipped_frames_on_main_tid)
        or !writeSimpleType(header.python_allocator) or !writeSimpleType(header.trace_python_allocators)
        or !writeSimpleType(header.track_object_lifetimes))
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
    auto token = static_cast<unsigned char>(RecordType::TRAILER);
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
            d_header.native_traces,
            d_header.trace_python_allocators,
            d_header.track_object_lifetimes);
}

AggregatingRecordWriter::AggregatingRecordWriter(
        std::unique_ptr<memray::io::Sink> sink,
        const std::string& command_line,
        bool native_traces,
        bool trace_python_allocators,
        bool track_object_lifetimes)
: RecordWriter(std::move(sink))
{
    memcpy(d_header.magic, MAGIC, sizeof(d_header.magic));
    d_header.version = CURRENT_HEADER_VERSION;
    d_header.python_version = PY_VERSION_HEX;
    d_header.native_traces = native_traces;
    d_header.file_format = FileFormat::AGGREGATED_ALLOCATIONS;
    d_header.command_line = command_line;
    d_header.pid = ::getpid();
    d_header.python_allocator = getPythonAllocator();
    d_header.trace_python_allocators = trace_python_allocators;
    d_header.track_object_lifetimes = track_object_lifetimes;

    d_stats.start_time = duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

void
AggregatingRecordWriter::setMainTidAndSkippedFrames(
        thread_id_t main_tid,
        size_t skipped_frames_on_main_tid)
{
    d_header.main_tid = main_tid;
    d_header.skipped_frames_on_main_tid = skipped_frames_on_main_tid;
}

bool
AggregatingRecordWriter::writeHeader(bool seek_to_start)
{
    // Nothing to do; everything is written by writeTrailer.
    (void)seek_to_start;
    return true;
}

bool
AggregatingRecordWriter::writeTrailer()
{
    d_stats.end_time = duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
    d_header.stats = d_stats;
    if (!writeHeaderCommon(d_header)) {
        return false;
    }

    for (const auto& memory_snapshot : d_memory_snapshots) {
        if (!writeSimpleType(AggregatedRecordType::MEMORY_SNAPSHOT) || !writeSimpleType(memory_snapshot))
        {
            return false;
        }
    }

    for (const auto& [tid, thread_name] : d_thread_name_by_tid) {
        if (!writeSimpleType(AggregatedRecordType::CONTEXT_SWITCH)
            || !writeSimpleType(ContextSwitch{tid})
            || !writeSimpleType(AggregatedRecordType::THREAD_RECORD)
            || !writeString(thread_name.c_str()))
        {
            return false;
        }
    }

    for (const auto& mappings : d_mappings_by_generation) {
        if (!writeMappingsCommon(mappings)) {
            return false;
        }
    }

    // Write code objects first
    for (const auto& [code_id, code_info] : d_code_objects_by_id) {
        if (!writeSimpleType(AggregatedRecordType::CODE_OBJECT) || !writeVarint(code_id)
            || !writeString(code_info.function_name.c_str()) || !writeString(code_info.filename.c_str())
            || !writeIntegralDelta(&d_last.code_firstlineno, code_info.firstlineno)
            || !writeVarint(code_info.linetable.size())
            || !d_sink->writeAll(code_info.linetable.data(), code_info.linetable.size()))
        {
            return false;
        }
    }

    UnresolvedNativeFrame last{};
    for (const auto& record : d_native_frames) {
        if (!writeSimpleType(AggregatedRecordType::NATIVE_TRACE_INDEX)
            || !writeIntegralDelta(&last.ip, record.ip)
            || !writeIntegralDelta(&last.index, record.index))
        {
            return false;
        }
    }

    for (size_t frame_id = 0; frame_id < d_python_frame_registry.size(); ++frame_id) {
        const auto& frame = d_python_frame_registry.getRecord(frame_id);
        if (!writeSimpleType(AggregatedRecordType::PYTHON_FRAME_INDEX) || !writeVarint(frame_id)
            || !writeVarint(frame.code_object_id) || !writeSignedVarint(frame.instruction_offset)
            || !writeSimpleType(frame.is_entry_frame))
        {
            return false;
        }
    }

    for (FrameTree::index_t index = d_python_frame_tree.minIndex();
         index <= d_python_frame_tree.maxIndex();
         ++index)
    {
        auto [frame_id, parent_index] = d_python_frame_tree.nextNode(index);

        if (!writeSimpleType(AggregatedRecordType::PYTHON_TRACE_INDEX) || !writeVarint(frame_id)
            || !writeVarint(parent_index))
        {
            return false;
        }
    }

    // Write surviving objects
    for (const auto& [address, native_frame_id] : d_surviving_objects) {
        if (!writeSimpleType(AggregatedRecordType::SURVIVING_OBJECT) || !writeVarint(address >> 3)
            || (d_header.native_traces && !writeVarint(native_frame_id)))
        {
            return false;
        }
    }

    d_high_water_mark_aggregator.visitAllocations([&](const AggregatedAllocation& allocation) {
        if (allocation.n_allocations_in_high_water_mark == 0 && allocation.n_allocations_leaked == 0) {
            return true;
        }

        return writeSimpleType(AggregatedRecordType::AGGREGATED_ALLOCATION)
               && writeSimpleType(allocation);
    });

    // The FileSource will ignore trailing 0x00 bytes. This non-zero trailer
    // marks the boundary between bytes we wrote and padding bytes.
    if (!writeSimpleType(AggregatedRecordType::AGGREGATED_TRAILER)) {
        return false;
    }

    return true;
}

std::unique_ptr<RecordWriter>
AggregatingRecordWriter::cloneInChildProcess()
{
    std::unique_ptr<io::Sink> new_sink = d_sink->cloneInChildProcess();
    if (!new_sink) {
        return {};
    }
    return std::make_unique<AggregatingRecordWriter>(
            std::move(new_sink),
            d_header.command_line,
            d_header.native_traces,
            d_header.trace_python_allocators,
            d_header.track_object_lifetimes);
}

bool
AggregatingRecordWriter::writeRecord(const MemoryRecord& record)
{
    MemorySnapshot snapshot{
            record.ms_since_epoch,
            record.rss,
            d_high_water_mark_aggregator.getCurrentHeapSize()};
    d_memory_snapshots.push_back(snapshot);
    return true;
}

bool
AggregatingRecordWriter::writeRecord(const pycode_map_val_t& item)
{
    // For aggregating writer, we'll store code objects in a map
    const auto& [code_id, code_info] = item;
    d_code_objects_by_id.emplace(code_id, code_info);
    return true;
}

bool
AggregatingRecordWriter::writeRecord(const UnresolvedNativeFrame& record)
{
    d_native_frames.emplace_back(record);
    return true;
}

bool
AggregatingRecordWriter::writeMappings(const std::vector<ImageSegments>& mappings)
{
    d_mappings_by_generation.push_back(mappings);
    return true;
}

bool
AggregatingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const FramePop& record)
{
    auto count = record.count;
    auto& stack = d_python_stack_ids_by_thread[tid];
    assert(stack.size() >= record.count);
    while (count) {
        count -= 1;
        stack.pop_back();
    }
    return true;
}

bool
AggregatingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const FramePush& record)
{
    auto [it, inserted] = d_python_stack_ids_by_thread.emplace(tid, python_stack_ids_t{});
    auto& stack = it->second;
    if (inserted) {
        stack.reserve(1024);
    }
    auto frame_index = d_python_frame_registry.registerRecord(record.frame).first;
    FrameTree::index_t current_stack_id = stack.empty() ? 0 : stack.back();
    FrameTree::index_t new_stack_id = d_python_frame_tree.getTraceIndex(current_stack_id, frame_index);
    stack.push_back(new_stack_id);
    return true;
}

bool
AggregatingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const AllocationRecord& record)
{
    Allocation allocation;
    allocation.tid = tid;
    allocation.address = record.address;
    allocation.size = record.size;
    allocation.allocator = record.allocator;
    allocation.native_frame_id = record.native_frame_id;
    if (!hooks::isDeallocator(record.allocator)) {
        auto& stack = d_python_stack_ids_by_thread[tid];
        allocation.frame_index = stack.empty() ? 0 : stack.back();
    } else {
        allocation.frame_index = 0;
    }
    allocation.native_segment_generation = d_mappings_by_generation.size();
    allocation.n_allocations = 1;
    d_high_water_mark_aggregator.addAllocation(allocation);
    return true;
}

bool
AggregatingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const ThreadRecord& record)
{
    d_thread_name_by_tid[tid] = record.name;
    return true;
}

bool
AggregatingRecordWriter::writeThreadSpecificRecord(thread_id_t tid, const ObjectRecord& record)
{
    if (record.is_created) {
        d_surviving_objects[record.address] = record.native_frame_id;
    } else {
        d_surviving_objects.erase(record.address);
    }
    return true;
}

}  // namespace memray::tracking_api
