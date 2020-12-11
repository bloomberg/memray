
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
struct hash<pensieve::tracking_api::RawFrame>
{
    std::size_t operator()(pensieve::tracking_api::RawFrame const& frame) const noexcept
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
struct hash<pensieve::tracking_api::Frame>
{
    std::size_t operator()(pensieve::tracking_api::Frame const& frame) const noexcept
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
add_frame(frame_map_t& frame_map, const RawFrame& frame)
{
    frame_id_t id = std::hash<RawFrame>{}(frame);
    frame_map[id] = frame;
    return id;
}

size_t
str_hash(const char* val)
{
    static const size_t shift = (size_t)log2(1 + sizeof(char*));
    return (size_t)(val) >> shift;
}

}  // namespace pensieve::tracking_api
