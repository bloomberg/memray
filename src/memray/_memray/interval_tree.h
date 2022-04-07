#pragma once

#include <algorithm>
#include <iostream>
#include <optional>
#include <unordered_map>
#include <vector>

namespace memray {
struct Range
{
    Range(uintptr_t start, uintptr_t end);
    [[nodiscard]] std::optional<Range> intersection(const Range& other) const;
    [[nodiscard]] size_t size() const;

    uintptr_t start;
    uintptr_t end;
};

template<typename T>
class IntervalTree
{
  private:
    using ranges_t = std::vector<std::pair<Range, T>>;
    ranges_t d_ranges;

  public:
    using const_iterator = typename ranges_t::const_iterator;
    using iterator = typename ranges_t::iterator;

    void add(uintptr_t start, size_t size, const T& element)
    {
        if (size <= 0) {
            return;
        }
        d_ranges.emplace_back(Range(start, start + size), element);
    }
    std::optional<std::vector<std::pair<Range, T>>> remove(uintptr_t start, size_t size)
    {
        if (size <= 0) {
            return std::nullopt;
        }

        std::vector<std::pair<Range, T>> new_ranges;
        std::vector<std::pair<Range, T>> removed;
        auto remove = Range(start, start + size);
        for (auto& [range, value] : d_ranges) {
            std::optional<Range> intersection = range.intersection(remove);
            // This range doesn't contain the element to remove, so don't remove anything
            if (!intersection) {
                new_ranges.emplace_back(range, value);
                continue;
            }
            // The interval completely overlaps with this range: remove it entirely
            if ((intersection->start == range.start) && (intersection->end == range.end)) {
                removed.emplace_back(intersection.value(), value);
            }
            // Remove a piece of the interval from the start:
            else if ((intersection->start == range.start) && (intersection->end < range.end))
            {
                auto new_range = Range(intersection->end, range.end);
                new_ranges.emplace_back(new_range, value);
                removed.emplace_back(intersection.value(), value);
            }
            // Remove a piece of the interval from the end:
            else if ((intersection->start > range.start) && (intersection->end == range.end))
            {
                auto new_range = Range(range.start, intersection->start);
                new_ranges.emplace_back(new_range, value);
                removed.emplace_back(intersection.value(), value);
            }
            // Remove a piece of the interval from the middle, splitting the interval in two
            else
            {
                new_ranges.emplace_back(Range(range.start, intersection->start), value);
                new_ranges.emplace_back(Range(intersection->end, range.end), value);
                removed.emplace_back(intersection.value(), value);
            }
        }

        d_ranges = new_ranges;

        if (removed.empty()) {
            return std::nullopt;
        }
        return removed;
    }
    size_t size()
    {
        size_t result = 0;
        std::for_each(d_ranges.begin(), d_ranges.end(), [&](const auto& pair) {
            result += pair.first.size();
        });
        return result;
    }

    iterator begin()
    {
        return d_ranges.begin();
    }

    iterator end()
    {
        return d_ranges.end();
    }

    const_iterator cbegin()
    {
        return d_ranges.cbegin();
    }

    const_iterator cend()
    {
        return d_ranges.cend();
    }
};

}  // namespace memray
