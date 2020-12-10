
#include "records.h"

#include <cstring>

namespace {
/**
 * Custom hash function to uniquely identify frames based on the function, file and line number.
 *
 * See https://stackoverflow.com/a/38140932.
 */
inline void
hash_combine([[maybe_unused]] std::size_t& seed)
{
}

template<typename T, typename... Rest>
inline void
hash_combine(std::size_t& seed, const T& v, Rest... rest)
{
    std::hash<T> hasher;
    seed ^= hasher(v) + 0x9e3779b9 + (seed << 6) + (seed >> 2);
    hash_combine(seed, rest...);
}

}  // anonymous namespace

namespace std {
template<>
struct hash<pensieve::tracking_api::Frame>
{
    std::size_t operator()(pensieve::tracking_api::Frame const& frame) const noexcept
    {
        // Keep this hashing fast and simple as this has a non trivial
        // performance impact on the tracing functionality.
        auto func = reinterpret_cast<size_t>(frame.function_name);
        auto filename = reinterpret_cast<size_t>(frame.filename);
        auto lineno = reinterpret_cast<size_t>(frame.lineno);
        return func ^ filename ^ lineno;
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
        std::size_t result = 0;
        hash_combine(result, func, file, frame.lineno);
        return result;
    }
};

}  // namespace std

namespace pensieve::tracking_api {

frame_id_t
add_frame(frame_map_t& frame_map, const Frame& frame)
{
    frame_id_t id = std::hash<Frame>{}(frame);
    frame_map[id] = frame;
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
operator<<(std::ostream& ostream, const FrameSeqEntry& frame_seq)
{
    ostream << TOKEN_FRAME_INDEX << " " << frame_seq.frame_id << " " << frame_seq.tid << " "
            << frame_seq.action << "\n";
    return ostream;
}

std::istream&
operator>>(std::istream& istream, FrameSeqEntry& frame_seq)
{
    int action;
    if (!(istream >> frame_seq.frame_id >> frame_seq.tid >> action)) {
        // TODO add logging
        throw std::runtime_error("Failed to parse frame sequence");
    }
    frame_seq.action = static_cast<FrameAction>(action);
    return istream;
}

}  // namespace pensieve::tracking_api
