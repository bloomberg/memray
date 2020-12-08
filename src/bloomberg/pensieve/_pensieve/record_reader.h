#pragma once

#include "record_reader.h"
#include "records.h"

#include <fstream>

namespace pensieve::api {

class RecordReader
{
  public:
    explicit RecordReader(const std::string& file_name);

    const std::vector<tracking_api::PyAllocationRecord>& results() const;

  private:
    void parse();
    std::pair<std::string, std::string> get_frame(const tracking_api::frame_id_t frame_id) const;

    std::ifstream d_input;
    std::vector<tracking_api::PyAllocationRecord> d_records;
    std::map<tracking_api::os_thread_id_t, tracking_api::pyframe_map_t> d_thread_frame_mapping;
    tracking_api::pyframe_map_t d_frame_map;
};

}  // namespace pensieve::api
