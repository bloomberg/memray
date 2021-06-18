#include "interval_tree.h"

namespace pensieve {

Range::Range(uintptr_t start, uintptr_t end)
: start(start)
, end(end){};

std::optional<Range>
Range::intersection(const Range& other) const
{
    auto max_start = std::max(start, other.start);
    auto min_end = std::min(end, other.end);
    if (min_end <= max_start) {
        return std::nullopt;
    } else {
        return Range(max_start, min_end);
    }
}

size_t
Range::size() const
{
    return end - start;
}

}  // namespace pensieve
