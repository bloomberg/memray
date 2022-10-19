#include <cstring>
#include <iostream>
#include <utility>

#include "native_resolver.h"

#include "logging.h"

namespace memray::native_resolver {

#ifdef __APPLE__
static const logLevel RESOLVE_LIB_LOG_LEVEL = DEBUG;
#else
static const logLevel RESOLVE_LIB_LOG_LEVEL = WARNING;
#endif

StringStorage::StringStorage()
{
    d_interned_data.reserve(4096);
    d_interned_data_storage.reserve(4096);
}

size_t
StringStorage::internString(const std::string& str, const char** interned_string)
{
    if (str.empty()) {
        return 0;
    }

    const size_t id = d_interned_data.size() + 1;
    auto inserted = d_interned_data.insert({str, id});
    if (interned_string) {
        *interned_string = inserted.first->first.c_str();
    }

    if (!inserted.second) {
        return inserted.first->second;
    }
    //  C++11 standard § 23.2.5/8: Rehashing the elements of an unordered associative container
    //  invalidates iterators, changes ordering between elements, and changes which buckets elements
    //  appear in, but does not invalidate pointers or references to elements.
    d_interned_data_storage.push_back(&inserted.first->first);

    return id;
}

const std::string&
StringStorage::resolveString(size_t index) const
{
    assert(index != 0);
    return *d_interned_data_storage.at(index - 1);
}

MemorySegment::MemorySegment(
        std::string filename,
        uintptr_t start,
        uintptr_t end,
        backtrace_state* state,
        size_t filename_index)
: d_filename(std::move(filename))
, d_start(start)
, d_end(end)
, d_index(filename_index)
, d_state(state)
{
}

static std::string
demangle(const char* function)
{
    if (!function) {
        return {};
    } else if (function[0] != '_' || function[1] != 'Z') {
        return {function};
    }

    std::string ret;
    int status = 0;
    char* demangled = abi::__cxa_demangle(function, nullptr, nullptr, &status);
    if (demangled != nullptr) {
        ret = demangled;
        free(demangled);
    } else {
        ret = function;
    }
    return ret;
}

void
MemorySegment::resolveFromSymbolTable(uintptr_t address, MemorySegment::ExpandedFrame& expanded_frame)
        const
{
    struct CallbackData
    {
        ExpandedFrame* expanded_frame;
        const MemorySegment* segment;
        uintptr_t address;
    };
    CallbackData data = {&expanded_frame, this, address};

    auto callback = [](void* data, uintptr_t, const char* symbol, uintptr_t, uintptr_t) {
        const std::string the_symbol = demangle(symbol);
        auto the_data = reinterpret_cast<CallbackData*>(data);
        the_data->expanded_frame->push_back(
                Frame{the_symbol.empty() ? "<unknown>" : the_symbol, "<unknown>", 0});
    };
    auto error_callback = [](void* _data, const char* msg, int errnum) {
        auto* data = reinterpret_cast<const CallbackData*>(_data);
        LOG(ERROR) << "Error getting backtrace for address " << std::hex << data->address << std::dec
                   << " in segment " << data->segment->d_filename << " (errno " << errnum
                   << "): " << msg;
    };
    backtrace_syminfo(d_state, address, callback, error_callback, &data);
}

void
MemorySegment::resolveFromDebugInfo(uintptr_t address, MemorySegment::ExpandedFrame& expanded_frame)
        const
{
    auto callback =
            [](void* data, uintptr_t /*addr*/, const char* file, int line, const char* symbol) -> int {
        const std::string the_symbol = demangle(symbol);
        if (the_symbol.empty()) {
            return 0;
        }
        Frame frame{the_symbol, file ? file : "<unknown>", line};
        auto expanded_frame = reinterpret_cast<ExpandedFrame*>(data);
        expanded_frame->push_back(frame);
        return 0;
    };
    auto error_callback = [](void* data, const char*, int) {
        auto expanded_frame = reinterpret_cast<ExpandedFrame*>(data);
        // Ensure that on failure we fall back to the symbol table approach if the regular
        // callback has been called previously.
        expanded_frame->clear();
    };
    backtrace_pcinfo(d_state, address, callback, error_callback, &expanded_frame);
}

MemorySegment::ExpandedFrame
MemorySegment::resolveIp(uintptr_t address) const
{
    ExpandedFrame expanded_frame{};
    assert(d_state != nullptr);
    // libbacktrace expects a program counter that is 1 byte less than the one produced by
    // libunwind (and any other unwinder that I tested). This is because libbacktrace's native
    // unwinder does indeed produce program counters with one byte less for some reason and
    // libbacktrace's symbolizer is prepared to work with libbacktrace's machinery convention.
    uintptr_t corrected_address = address - 1;
    resolveFromDebugInfo(corrected_address, expanded_frame);
    if (expanded_frame.empty()) {
        resolveFromSymbolTable(corrected_address, expanded_frame);
    }
    return expanded_frame;
}

bool
MemorySegment::operator<(const MemorySegment& segment) const
{
    return std::tie(d_start, d_end, d_index) < std::tie(segment.d_start, segment.d_end, segment.d_index);
}

bool
MemorySegment::operator!=(const MemorySegment& segment) const
{
    return std::tie(d_start, d_end, d_index)
           != std::tie(segment.d_start, segment.d_end, segment.d_index);
}

bool
MemorySegment::isAddressInRange(uintptr_t addr) const
{
    return d_start <= addr && d_end > addr;
}

uintptr_t
MemorySegment::start() const
{
    return d_start;
}

uintptr_t
MemorySegment::end() const
{
    return d_end;
}

uintptr_t
MemorySegment::filenameIndex() const
{
    return d_index;
}

const std::string&
MemorySegment::filename() const
{
    return d_filename;
}

ResolvedFrame::ResolvedFrame(
        const MemorySegment::Frame& frame,
        const std::shared_ptr<StringStorage>& d_string_storage)
: d_string_storage(d_string_storage)
, d_symbol_index(d_string_storage->internString(frame.symbol))
, d_file_index(d_string_storage->internString(frame.filename))
, d_line(frame.lineno)
{
}

const std::string&
ResolvedFrame::Symbol() const
{
    return d_string_storage->resolveString(d_symbol_index);
}

const std::string&
ResolvedFrame::File() const
{
    return d_string_storage->resolveString(d_file_index);
}

int
ResolvedFrame::Line() const
{
    return d_line;
}
PyObject*
ResolvedFrame::toPythonObject(python_helpers::PyUnicode_Cache& pystring_cache) const
{
    PyObject* pyfunction_name = pystring_cache.getUnicodeObject(Symbol());  // Borrowed
    if (pyfunction_name == nullptr) {
        return nullptr;
    }
    PyObject* pyfilename = pystring_cache.getUnicodeObject(File());  // Borrowed
    if (pyfilename == nullptr) {
        return nullptr;
    }
    PyObject* pylineno = PyLong_FromLong(Line());
    if (pylineno == nullptr) {
        return nullptr;
    }
    PyObject* tuple = PyTuple_New(3);
    if (tuple == nullptr) {
        Py_DECREF(pylineno);
        return nullptr;
    }
    Py_INCREF(pyfunction_name);
    Py_INCREF(pyfilename);
    PyTuple_SET_ITEM(tuple, 0, pyfunction_name);
    PyTuple_SET_ITEM(tuple, 1, pyfilename);
    PyTuple_SET_ITEM(tuple, 2, pylineno);
    return tuple;
}

const std::string&
ResolvedFrames::memoryMap() const
{
    return d_string_storage->resolveString(d_memory_map_index);
}

const std::vector<ResolvedFrame>&
ResolvedFrames::frames() const
{
    return d_frames;
}

SymbolResolver::SymbolResolver()
{
    d_backtrace_states.reserve(PREALLOCATED_BACKTRACE_STATES);
    d_resolved_ips_cache.reserve(PREALLOCATED_IPS_CACHE_ITEMS);
}

template<typename T>
static auto
findModule(const uintptr_t ip, const T& segments)
{
    return lower_bound(
            segments.begin(),
            segments.end(),
            ip,
            [](const MemorySegment& segment, const uintptr_t ip) { return segment.end() < ip; });
}

SymbolResolver::resolved_frames_t
SymbolResolver::resolve(uintptr_t ip, size_t generation)
{
    // Check if we have resolved this frame previously
    auto it = d_resolved_ips_cache.find({ip, generation});
    if (it == d_resolved_ips_cache.end()) {
        // This is the first time we resolved this frame, do the actual resolution
        // work and insert it into the cache.
        auto resolved_frames = resolveFromSegments(ip, generation);
        it = d_resolved_ips_cache.emplace(ips_cache_pair_t(ip, generation), resolved_frames).first;
    }
    return it->second;
}

SymbolResolver::resolved_frames_t
SymbolResolver::resolveFromSegments(uintptr_t ip, size_t generation)
{
    if (d_are_segments_dirty) {
        // Sort the segments so the binary search below works
        sort(currentSegments().begin(), currentSegments().end());
        d_are_segments_dirty = false;
    }

    const auto& segments = d_segments.at(generation);
    auto segment = findModule(ip, segments);
    if (segment == segments.end() || !segment->isAddressInRange(ip)) {
        return nullptr;
    }

    std::vector<ResolvedFrame> frames;
    const auto expanded_frame = segment->resolveIp(ip);
    if (expanded_frame.empty()) {
        return nullptr;
    }
    auto segment_index = segment->filenameIndex();
    std::transform(
            expanded_frame.begin(),
            expanded_frame.end(),
            std::back_inserter(frames),
            [this](const auto& frame) {
                return ResolvedFrame{frame, d_string_storage};
            });
    return std::make_shared<ResolvedFrames>(segment_index, std::move(frames), d_string_storage);
}

void
SymbolResolver::addSegment(
        const std::string& filename,
        backtrace_state* backtrace_state,
        const size_t filename_index,
        const uintptr_t address_start,
        const uintptr_t address_end)
{
    currentSegments()
            .emplace_back(filename, address_start, address_end, backtrace_state, filename_index);
    d_are_segments_dirty = true;
}

void
SymbolResolver::addSegments(
        const std::string& filename,
        uintptr_t addr,
        const std::vector<tracking_api::Segment>& segments)
{
    // We use a char* for the filename to reduce the memory footprint and
    // because the libbacktrace callback in findBacktraceState operates on char*
    const char* interned_filename = nullptr;
    auto filename_index = d_string_storage->internString(filename, &interned_filename);

    auto state = findBacktraceState(interned_filename, addr);
    if (state == nullptr) {
        LOG(RESOLVE_LIB_LOG_LEVEL) << "Failed to prepare a backtrace state for " << filename;
        return;
    }

    for (const auto& segment : segments) {
        const uintptr_t segment_start = addr + segment.vaddr;
        const uintptr_t segment_end = addr + segment.vaddr + segment.memsz;
        addSegment(filename, state, filename_index, segment_start, segment_end);
    }
}

void
SymbolResolver::clearSegments()
{
    if (d_are_segments_dirty) {
        // Sort the segments so the binary search in resolve() works
        sort(currentSegments().begin(), currentSegments().end());
    }
    size_t reserve_size = 256;
    if (currentSegmentGeneration() > 0) {
        reserve_size = currentSegments().size();
    }
    d_segments[currentSegmentGeneration() + 1].reserve(reserve_size);
}

backtrace_state*
SymbolResolver::findBacktraceState(const char* filename, uintptr_t address_start)
{
    // We hash into "d_backtrace_states" using a char* as it's safe on the condition that every
    // const char* used as a key in the map is one that was returned by "d_string_storage",
    // and it's safe because no pointer that's returned by "d_string_storage" is ever invalidated.
    auto it = d_backtrace_states.find(filename);
    if (it != d_backtrace_states.end()) {
        return it->second;
    }

    struct CallbackData
    {
        const char* fileName;
    };
    CallbackData data = {filename};

    auto errorHandler = [](void* rawData, const char* msg, int errnum) {
        auto data = reinterpret_cast<const CallbackData*>(rawData);
        LOG(RESOLVE_LIB_LOG_LEVEL) << "Error creating backtrace state for segment " << data->fileName
                                   << "(errno " << errnum << "): " << msg;
    };

    auto state = backtrace_create_state(data.fileName, false, errorHandler, &data);

    if (!state) {
        return nullptr;
    }

    const int descriptor = backtrace_open(data.fileName, errorHandler, &data, nullptr);
    if (descriptor >= 1) {
        int foundSym = 0;
#ifdef __linux__
        int foundDwarf = 0;
        auto ret =
                elf_add(state,
                        data.fileName,
                        descriptor,
                        nullptr,
                        0,
                        address_start,
                        errorHandler,
                        &data,
                        &state->fileline_fn,
                        &foundSym,
                        &foundDwarf,
                        nullptr,
                        false,
                        false,
                        nullptr,
                        0);
        state->syminfo_fn = (ret && foundSym) ? &elf_syminfo : &elf_nosyms;
#elif defined(__APPLE__)
        auto ret = macho_add(
                state,
                data.fileName,
                descriptor,
                0,
                nullptr,
                address_start,
                0,
                errorHandler,
                &data,
                &state->fileline_fn,
                &foundSym);
        state->syminfo_fn = (ret && foundSym) ? &macho_syminfo : &macho_nosyms;
#else
        return nullptr;
#endif
    }
    d_backtrace_states.insert(it, {filename, state});
    return state;
}

std::vector<MemorySegment>&
SymbolResolver::currentSegments()
{
    return d_segments.at(d_segments.size());
}

size_t
SymbolResolver::currentSegmentGeneration() const
{
    return d_segments.size();
}

std::vector<std::string>
unwindHere()
{
    struct CallbackData
    {
        std::vector<std::string> frames;
        struct backtrace_state* state;
    };

    auto err_callback = [](void* data, const char* msg, int errnum) { return; };

    auto callback = [](void* vdata, uintptr_t pc, const char* filename, int lineno, const char* function)
            -> int {
        auto result = reinterpret_cast<CallbackData*>(vdata);
        std::string the_function = function ? function : "";
        std::string the_filename = filename ? filename : "";
        if (!function && !filename) {
            // Fallback callbacks for when we can't get a filename or function name via debug
            // information. These fallback callbacks query the symbol table instead.
            auto fallback_callback =
                    [](void* data, uintptr_t, const char* symbol, uintptr_t, uintptr_t) {
                        auto result = reinterpret_cast<std::vector<std::string>*>(data);
                        std::string the_function = symbol ? symbol : "";
                        result->push_back(the_function + "::");
                    };
            auto fallback_err_callback = [](void* data, const char* msg, int errnum) { return; };
            backtrace_syminfo(result->state, pc, fallback_callback, fallback_err_callback, vdata);
        } else {
            result->frames.push_back(the_function + ":" + the_filename + ":" + std::to_string(lineno));
        }
        return 0;
    };

    struct backtrace_state* state = backtrace_create_state("", 1, err_callback, nullptr);
    if (!state) {
        return {};
    }
    CallbackData data = {std::vector<std::string>(), state};
    ::backtrace_full(state, 0, callback, err_callback, &data);
    return data.frames;
}

}  // namespace memray::native_resolver
