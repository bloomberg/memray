#include "record_reader.h"
#include "records.h"

#include <deque>
#include <sstream>

namespace pensieve::api {

using namespace tracking_api;

namespace {

tracking_api::pyframe_map_t
read_frames(const std::string& file_name)
{
    std::ifstream ifs;
    ifs.open(file_name);
    tracking_api::pyframe_map_t frames;

    for (std::string line; std::getline(ifs, line);) {
        std::istringstream istream(line);
        if (!line.length() or line.at(0) != TOKEN_FRAME) {
            continue;
        }

        char token;
        istream >> token;
        if (token == TOKEN_FRAME) {
            pyframe_map_val_t pyframe_val;
            istream >> pyframe_val;
            frames[pyframe_val.first] = pyframe_val.second;
        }
    }
    return frames;
}
}  // namespace

RecordReader::RecordReader(const std::string& file_name)
{
    d_input.open(file_name);
    d_frame_map = read_frames(file_name);  // FIXME move into parse
    parse();
}

void
RecordReader::parse()
{
    d_records.clear();
    d_thread_frame_mapping.clear();

    // First pass
    stack_traces_t stack_traces;
    for (std::string line; std::getline(d_input, line);) {
        std::istringstream istream(line);
        if (!line.length() or line.at(0) == '#') {
            continue;
        }
        char token;
        istream >> token;

        switch (token) {
            case TOKEN_ALLOCATION:
                parseAllocation(stack_traces, istream);
                break;
            case TOKEN_FRAME_INDEX:
                parseFrame(stack_traces, istream);
                break;
        }
    }
}

void
RecordReader::parseFrame(stack_traces_t& stack_traces, std::istringstream& istream) const
{
    FrameSeqEntry frame_seq_entry{};
    istream >> frame_seq_entry;
    os_thread_id_t tid = frame_seq_entry.tid;

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
RecordReader::parseAllocation(stack_traces_t& stack_traces, std::istringstream& istream)
{
    AllocationRecord record;
    istream >> record;
    const auto stack = stack_traces.find(record.tid);
    PyAllocationRecord py_record{record.pid, record.tid, record.address, record.size, record.allocator};

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

const std::vector<PyAllocationRecord>&
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
