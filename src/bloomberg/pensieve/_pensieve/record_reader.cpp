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
    std::map<os_thread_id_t, std::deque<tracking_api::frame_id_t>> stack_traces;
    for (std::string line; std::getline(d_input, line);) {
        std::istringstream istream(line);
        if (!line.length() or line.at(0) == '#') {
            continue;
        }
        char token;
        istream >> token;

        if (token == TOKEN_ALLOCATION) {
            AllocationRecord record;
            istream >> record;
            const auto stack = stack_traces.find(record.tid);
            PyAllocationRecord
                    py_record{record.pid, record.tid, record.address, record.size, record.allocator};

            // We don't currently keep track of native frames, so we won't fill them in the record
            if (stack != stack_traces.end()) {
                for (const frame_id_t& frame_id : stack->second) {
                    PyFrame frame = d_frame_map[frame_id];
                    py_record.stack_trace.push_back(frame);
                }
                std::reverse(py_record.stack_trace.begin(), py_record.stack_trace.end());
            }

            d_records.push_back(py_record);
        } else if (token == TOKEN_FRAME_INDEX) {
            FrameSeqEntry frame_seq_entry{};
            istream >> frame_seq_entry;
            os_thread_id_t tid = frame_seq_entry.tid;

            // Allocate new stack for the thread in case it's the first time we see it
            if (stack_traces.find(tid) == stack_traces.end()) {
                stack_traces[tid] = std::deque<tracking_api::frame_id_t>();
            }

            if (frame_seq_entry.action == FrameAction::PUSH) {
                stack_traces[tid].push_front(frame_seq_entry.frame_id);
            } else if (frame_seq_entry.action == FrameAction::POP) {
                frame_id_t prev_frame_id = stack_traces[tid].front();
                if (get_frame(frame_seq_entry.frame_id) == get_frame(prev_frame_id)) {
                    stack_traces[tid].pop_front();
                }
            }
        }
    }
}

const std::vector<PyAllocationRecord>&
RecordReader::results() const
{
    return d_records;
}
std::pair<std::string, std::string>
RecordReader::get_frame(const frame_id_t frame_id) const
{
    auto frame = d_frame_map.find(frame_id);
    if (frame == d_frame_map.end()) {
        throw std::runtime_error("Frame mismatch");
    }
    std::string func_name = frame->second.function_name;
    std::string file_name = frame->second.filename;

    return std::pair<std::string, std::string>(func_name, file_name);
}

}  // namespace pensieve::api
