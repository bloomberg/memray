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

    std::ifstream d_input;
    std::vector<tracking_api::PyAllocationRecord> d_records;
    tracking_api::pyframe_map_t d_frame_map;
};

}  // namespace pensieve::api
