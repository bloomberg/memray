#pragma once

#include "record_reader.h"
#include "records.h"

#include <deque>
#include <fstream>

namespace pensieve::api {

class RecordReader
{
  public:
    explicit RecordReader(const std::string& file_name);
    const std::vector<tracking_api::PyAllocationRecord>& results() const;

  private:
    // Aliases
    using frame_map_t = std::map<tracking_api::os_thread_id_t, tracking_api::pyframe_map_t>;
    using stack_traces_t = std::map<tracking_api::os_thread_id_t, std::deque<tracking_api::frame_id_t>>;

    // Data members
    std::ifstream d_input;
    std::vector<tracking_api::PyAllocationRecord> d_records;
    frame_map_t d_thread_frame_mapping;
    tracking_api::pyframe_map_t d_frame_map;

    // Methods
    void parse();
    std::pair<std::string, std::string> getFrameKey(tracking_api::frame_id_t frame_id) const;
    void parseAllocation(stack_traces_t& stack_traces, std::istringstream& istream);
    void parseFrame(stack_traces_t& stack_traces, std::istringstream& istream) const;
};

}  // namespace pensieve::api
