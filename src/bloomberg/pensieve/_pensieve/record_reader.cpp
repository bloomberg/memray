#include "record_reader.h"
#include "records.h"

#include <deque>
#include <sstream>

#include "hooks.h"

namespace pensieve::api {

using namespace tracking_api;

namespace {

tracking_api::pyframe_map_t
read_frames(const std::string& file_name)
{
    std::ifstream ifs;
    ifs.open(file_name);
    tracking_api::pyframe_map_t frames;

    auto parseFrameIndex = [&]() {
        tracking_api::pyframe_map_val_t pyframe_val;
        ifs.read((char*)&pyframe_val.first, sizeof(pyframe_val.first));
        std::getline(ifs, pyframe_val.second.function_name, '\0');
        std::getline(ifs, pyframe_val.second.filename, '\0');
        ifs.read((char*)&pyframe_val.second.lineno, sizeof(pyframe_val.second.lineno));
        auto iterator = frames.insert(pyframe_val);
        if (!iterator.second) {
            throw std::runtime_error("Two entries with the same ID found!");
        }
    };

    while (ifs.peek() != EOF) {
        RecordType record_type;
        ifs.read(reinterpret_cast<char*>(&record_type), sizeof(RecordType));
        switch (record_type) {
            case RecordType::ALLOCATION:
                ifs.seekg(static_cast<int>(ifs.tellg()) + sizeof(RawAllocationRecord));
                break;
            case RecordType::FRAME:
                ifs.seekg(static_cast<int>(ifs.tellg()) + sizeof(FrameSeqEntry));
                break;
            case RecordType::FRAME_INDEX:
                parseFrameIndex();
                break;
            default:
                throw std::runtime_error("Invalid record type");
        }
    }
    ifs.close();
    return frames;
}
}  // namespace

RecordReader::RecordReader(const std::string& file_name)
{
    d_input.open(file_name, std::ios::binary | std::ios::in);
    d_frame_map = read_frames(file_name);  // FIXME move into parse
    parse();
}

void
RecordReader::parse()
{
    d_records.clear();
    d_thread_frame_mapping.clear();

    stack_traces_t stack_traces;
    bool in_relevant_section = true;
    while (d_input.peek() != EOF && in_relevant_section) {
        RecordType record_type;
        d_input.read(reinterpret_cast<char*>(&record_type), sizeof(RecordType));
        switch (record_type) {
            case RecordType::ALLOCATION:
                parseAllocation(stack_traces);
                break;
            case RecordType::FRAME:
                parseFrame(stack_traces);
                break;
            case RecordType::FRAME_INDEX:
                in_relevant_section = false;
                break;
            default:
                throw std::runtime_error("Invalid record type");
        }
    }
}

void
RecordReader::parseFrame(stack_traces_t& stack_traces)
{
    FrameSeqEntry frame_seq_entry{};
    d_input.read(reinterpret_cast<char*>(&frame_seq_entry), sizeof(FrameSeqEntry));
    thread_id_t tid = frame_seq_entry.tid;

    auto isCoherentPop = [&](const auto& stack_traces, const auto& frame_entry) {
        frame_id_t prev_frame_id = stack_traces.at(frame_entry.tid).front();
        return getFrameKey(frame_entry.frame_id) == getFrameKey(prev_frame_id);
    };

    switch (frame_seq_entry.action) {
        case PUSH:
            stack_traces[tid].push_front(frame_seq_entry.frame_id);
            break;
        case POP:
            if (isCoherentPop(stack_traces, frame_seq_entry)) {
                stack_traces[tid].pop_front();
            }
            break;
    }
}

void
RecordReader::parseAllocation(stack_traces_t& stack_traces)
{
    RawAllocationRecord record{};
    d_input.read(reinterpret_cast<char*>(&record), sizeof(RawAllocationRecord));
    const auto stack = stack_traces.find(record.tid);
    AllocationRecord py_record{
            record.tid,
            record.address,
            record.size,
            allocator_to_string(static_cast<hooks::Allocator>(record.allocator))};

    // We don't currently keep track of native frames, so we won't fill them in the record
    if (stack != stack_traces.end()) {
        std::transform(
                stack->second.rbegin(),
                stack->second.rend(),
                std::back_inserter(py_record.stack_trace),
                [&](const auto& frame_id) { return d_frame_map[frame_id]; });
    }

    d_records.emplace_back(std::move(py_record));
}

const std::vector<AllocationRecord>&
RecordReader::results() const
{
    return d_records;
}
std::pair<std::string, std::string>
RecordReader::getFrameKey(frame_id_t frame_id) const
{
    auto frame = d_frame_map.find(frame_id);
    if (frame == d_frame_map.end()) {
        throw std::runtime_error("FrameId " + std::to_string(frame_id) + "could not be located");
    }
    std::string func_name = frame->second.function_name;
    std::string file_name = frame->second.filename;

    return std::pair<std::string, std::string>(func_name, file_name);
}

}  // namespace pensieve::api
