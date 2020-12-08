
#include "records.h"

#include <cstring>

namespace std {
template<>
struct hash<pensieve::tracking_api::Frame>
{
    std::size_t operator()(pensieve::tracking_api::Frame const& frame) const noexcept
    {
        using namespace pensieve::tracking_api;

        // TODO simply xor the pointers and the lineno
        std::size_t func = str_hash(frame.function_name);
        std::size_t file = str_hash(frame.filename);
        std::size_t h = 0;
        hash_combine(h, func, file, frame.lineno);
        return h;
    }
};

template<>
struct hash<pensieve::tracking_api::PyFrame>
{
    std::size_t operator()(pensieve::tracking_api::PyFrame const& frame) const noexcept
    {
        using namespace pensieve::tracking_api;

        std::hash<std::string> hasher;
        std::size_t func = hasher(frame.function_name);
        std::size_t file = hasher(frame.filename);
        std::size_t h = 0;
        hash_combine(h, func, file, frame.lineno);
        return h;
    }
};

}  // namespace std

namespace pensieve::tracking_api {

// FIXME This should be done automatically when hashing in our `std::map`
frame_id_t
add_frame(frame_map_t& frame_map, const Frame& frame)
{
    frame_id_t id = std::hash<Frame>{}(frame);
    if (frame_map.find(id) == frame_map.end()) {
        frame_map[id] = frame;
    }
    return id;
}

size_t
str_hash(const char* val)
{
    static const size_t shift = (size_t)log2(1 + sizeof(char*));
    return (size_t)(val) >> shift;
}

std::ostream&
operator<<(std::ostream& ostream, const AllocationRecord& record)
{
    ostream << TOKEN_ALLOCATION << " " << record.pid << " " << record.tid << " " << record.size << " "
            << record.address << " " << record.allocator << "\n";
    return ostream;
}

std::istream&
operator>>(std::istream& istream, AllocationRecord& record)
{
    if (!(istream >> record.pid >> record.tid >> record.size >> record.address >> record.allocator)) {
        // TODO add logging
        throw std::runtime_error("Failed to parse AllocationRecord");
    }

    return istream;
}

std::ostream&
operator<<(std::ostream& ostream, const PyFrame& frame)
{
    ostream << frame.function_name << " " << frame.filename << " " << frame.lineno << "\n";
    return ostream;
}

std::istream&
operator>>(std::istream& istream, PyFrame& frame)
{
    if (!(istream >> frame.function_name >> frame.filename >> frame.lineno)) {
        // TODO add logging
        throw std::runtime_error("Failed to parse PyFrame");
    }

    return istream;
}

std::ostream&
operator<<(std::ostream& ostream, const frame_map_t& frame_map)
{
    // We serialize the frames as PyFrames to simplify string writing/reading
    for (const auto& [id, frame] : frame_map) {
        ostream << TOKEN_FRAME << " " << id << " "
                << PyFrame{frame.function_name, frame.filename, frame.lineno};
    }
    return ostream;
}

std::istream&
operator>>(std::istream& istream, std::pair<frame_id_t, PyFrame>& frame_pair)
{
    if (!(istream >> frame_pair.first >> frame_pair.second)) {
        // TODO add logging
        throw std::runtime_error("Failed to parse AllocationRecord");
    }
    return istream;
}

std::ostream&
operator<<(std::ostream& ostream, const frame_seq_pair_t& frame_seq)
{
    ostream << TOKEN_FRAME_INDEX << " " << frame_seq.first << " " << frame_seq.second << "\n";
    return ostream;
}

std::istream&
operator>>(std::istream& istream, frame_seq_pair_t& frame_seq)
{
    int action;
    if (!(istream >> frame_seq.first >> action)) {
        // TODO add logging
        throw std::runtime_error("Failed to parse frame sequence");
    }
    frame_seq.second = static_cast<FrameAction>(action);
    return istream;
}

}  // namespace pensieve::tracking_api
