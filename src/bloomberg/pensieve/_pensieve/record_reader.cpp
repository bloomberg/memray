#include "record_reader.h"
#include "records.h"

#include <cstring>
#include <deque>
#include <sstream>

namespace pensieve::api {

using namespace tracking_api;

RecordReader::RecordReader(const std::string& file_name)
{
    d_input.open(file_name);
    parse();
}

void
RecordReader::parse()
{
    d_records.clear();
    d_frame_map.clear();
    std::vector<tracking_api::AllocationRecord> records;

    // First pass
    std::deque<tracking_api::frame_id_t> stack_trace;
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
            std::copy(stack_trace.begin(), stack_trace.end(), std::back_inserter(record.stack_trace));
            records.emplace_back(record);
        } else if (token == TOKEN_FRAME) {
            // These are at the end of the file, so we should have all indices by now
            pyframe_map_val_t pyframe_val;
            istream >> pyframe_val;
            d_frame_map[pyframe_val.first] = pyframe_val.second;
        } else if (token == TOKEN_FRAME_INDEX) {
            frame_seq_pair_t frame_seq_pair;
            istream >> frame_seq_pair;
            if (frame_seq_pair.second == FrameAction::PUSH) {
                stack_trace.push_front(frame_seq_pair.first);
            } else if (frame_seq_pair.second == FrameAction::POP) {
                stack_trace.pop_front();
            }
        }
    }

    // Second pass - resolve frame id's to frames
    std::vector<PyAllocationRecord> py_records;
    for (const AllocationRecord& record : records) {
        PyAllocationRecord
                py_record{record.pid, record.tid, record.address, record.size, record.allocator};
        for (const frame_id_t& frame_id : record.stack_trace) {
            PyFrame frame = d_frame_map[frame_id];
            py_record.stack_trace.push_back(frame);
        }
        d_records.push_back(py_record);
    }
}

const std::vector<PyAllocationRecord>&
RecordReader::results() const
{
    return d_records;
}

}  // namespace pensieve::api
