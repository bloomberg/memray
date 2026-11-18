#define PY_SSIZE_T_CLEAN
#include "greenlet_adapter.h"
#include "compat.h"
#include "python_stack_capture.h"
#include "tracking_api.h"
#include <Python.h>
#include <array>
#include <atomic>
#include <cstring>
#include <mutex>
#include <unordered_map>
#ifdef __APPLE__
#    include "macho_utils.h"
#endif
#if defined(__linux__) || defined(__APPLE__)
#    include <unistd.h>
#endif
#ifdef __linux__
#    include "tls_model.h"
#    include <link.h>
#endif

namespace memray::tracking_api::greenlet_adapter {
namespace {
struct GreenletPrefix
{
    PyObject_HEAD void* weakrefs;
    void* dict;
    void* implementation;
};
struct Registry
{
    std::mutex mutex;
    std::unordered_map<void*, uintptr_t> identities;
};
Registry* registry;
std::atomic<bool> active{};
std::atomic<uint64_t> module_generation{1};
std::atomic<bool> calibrated{};
std::atomic<bool> module_present{};
std::atomic<bool> identities_present{};
// Allocator callbacks advance this generation before an implementation
// address can be reused. Cached addresses are only compared, never read.
std::atomic<uint64_t> identity_generation{1};
std::array<std::atomic<uint64_t>, 256> identity_filter{};
struct CachedIdentity
{
    uint64_t generation{};
    void* implementation{};
    uintptr_t identity{};
};
MEMRAY_FAST_TLS thread_local CachedIdentity t_identity;
#ifdef MEMRAY_WITH_FRAME_MARKERS
MEMRAY_FAST_TLS thread_local uint64_t t_absent_generation;
#endif
std::atomic<uint64_t> checked_generation{};
#if defined(__linux__) || defined(__APPLE__)
struct TlsIndex
{
    size_t module;
    size_t offset;
};
TlsIndex tls_index{};
size_t tls_size;
size_t main_offset;
PyTypeObject* greenlet_type;
bool tls_uses_get_addr;
bool unsupported_warning;
std::atomic<uint64_t> single_module_generation{};
std::atomic<bool> single_module{};

bool
readGreenlet(uintptr_t address, GreenletPrefix& result, bool exact, PyTypeObject* expected_type)
{
    if (address < 4096
        || compat::copyReadableMemory(&result, reinterpret_cast<void*>(address), sizeof(result))
                   != sizeof(result)
        || !result.implementation)
    {
        return false;
    }
    auto* type = Py_TYPE(reinterpret_cast<PyObject*>(&result));
    for (unsigned depth = 0; type && depth < 32; ++depth) {
        if (type == expected_type) return true;
        if (exact) return false;
        PyTypeObject copied;
        if (compat::copyReadableMemory(&copied, type, sizeof(copied)) != sizeof(copied)) return false;
        type = copied.tp_base;
    }
    return false;
}

bool
mainOwnsState(uintptr_t main, void* implementation, uintptr_t state)
{
    // MainGreenlet ends with OwnedMainGreenlet _self, then the atomic
    // ThreadState* _thread_state. Check that ownership link without calling
    // a greenlet getter or assuming an offset within its C++ base class.
    uintptr_t copied[128];
    const auto words =
            compat::copyReadableMemory(copied, implementation, sizeof(copied)) / sizeof(uintptr_t);
    unsigned matches = 0;
    for (size_t index = 1; index < words; ++index) {
        matches += copied[index - 1] == main && copied[index] == state;
    }
    return matches == 1;
}

struct ModuleTls
{
    size_t module{};
    size_t size{};
    const char* data{};
    PyTypeObject* type{};
    bool unsupported{};
    bool found{};
    bool uses_get_addr{};
};

bool
setGreenletType(ModuleTls& result, uintptr_t address)
{
    PyTypeObject type;
    if (!address) {
        result.unsupported = true;
        return false;
    }
    if (compat::copyReadableMemory(&type, reinterpret_cast<void*>(address), sizeof(type))
        != sizeof(type))
        return false;
    constexpr char expected_name[] = "greenlet.greenlet";
    char name[sizeof(expected_name)];
    if (!type.tp_name || compat::copyReadableMemory(name, type.tp_name, sizeof(name)) != sizeof(name))
        return false;
    if (memcmp(name, expected_name, sizeof(expected_name)) != 0
        || type.tp_basicsize < static_cast<Py_ssize_t>(sizeof(GreenletPrefix))
        || type.tp_dictoffset != offsetof(GreenletPrefix, dict))
    {
        result.unsupported = true;
        return false;
    }
    result.type = reinterpret_cast<PyTypeObject*>(address);
    return true;
}

#    ifdef __linux__
void
copyTls(const dl_phdr_info* info, ModuleTls& result)
{
    result.found = true;
    result.module = info->dlpi_tls_modid;
    result.data = static_cast<const char*>(info->dlpi_tls_data);
    for (ElfW(Half) index = 0; index < info->dlpi_phnum; ++index) {
        if (info->dlpi_phdr[index].p_type == PT_TLS) result.size = info->dlpi_phdr[index].p_memsz;
    }
}

struct GreenletSymbols
{
    uintptr_t type{};
    uintptr_t initialize{};
    bool named{};

    bool present() const
    {
        return named || type || initialize;
    }
};

GreenletSymbols
greenletSymbols(const dl_phdr_info* info)
{
    const char* filename = strrchr(info->dlpi_name, '/');
    filename = filename ? filename + 1 : info->dlpi_name;
    GreenletSymbols result;
    result.named = strncmp(filename, "_greenlet.", 10) == 0;

    for (ElfW(Half) index = 0; index < info->dlpi_phnum; ++index) {
        const auto& segment = info->dlpi_phdr[index];
        if (segment.p_type != PT_DYNAMIC) continue;
        const auto* dynamic = reinterpret_cast<const Dyn*>(info->dlpi_addr + segment.p_vaddr);
        SymbolTable symbols(info->dlpi_addr, dynamic);
        result.type = symbols.getSymbolAddress("PyGreenlet_Type");
        result.initialize = symbols.getSymbolAddress("PyInit__greenlet");
        break;
    }
    // Direct ELF lookup returns only this module's defined exports. No dlsym,
    // dlopen, or dladdr call can acquire another loader lock in this callback.
    if (result.type && !moduleContains(info, result.type, sizeof(PyTypeObject))) result.type = 0;
    if (result.initialize && !moduleContains(info, result.initialize, 1)) result.initialize = 0;
    return result;
}

int
findModule(dl_phdr_info* info, size_t info_size, void* raw)
{
    const auto symbols = greenletSymbols(info);
    if (!symbols.present()) return 0;
    module_present.store(true, std::memory_order_release);
    if (info_size < offsetof(dl_phdr_info, dlpi_tls_data) + sizeof(info->dlpi_tls_data)) return 0;

    auto& result = *static_cast<ModuleTls*>(raw);
    if (!setGreenletType(result, symbols.type)) return 0;
    copyTls(info, result);
    result.uses_get_addr = usesGetAddrTls(info);
    return result.module && result.size;
}

struct GreenletModuleCount
{
    size_t expected_module;
    size_t count{};
    bool expected_found{};
};

int
countGreenletModules(dl_phdr_info* info, size_t info_size, void* raw)
{
    auto& result = *static_cast<GreenletModuleCount*>(raw);
    if (!greenletSymbols(info).present()) return 0;
    ++result.count;
    if (info_size >= offsetof(dl_phdr_info, dlpi_tls_modid) + sizeof(info->dlpi_tls_modid)
        && info->dlpi_tls_modid == result.expected_module)
    {
        result.expected_found = true;
    }
    return result.count > 1;
}

bool
isOnlyGreenletModule()
{
    const auto generation = module_generation.load(std::memory_order_acquire);
    if (single_module_generation.load(std::memory_order_acquire) == generation) {
        const bool only = single_module.load(std::memory_order_relaxed);
        return only && generation == module_generation.load(std::memory_order_acquire);
    }
    GreenletModuleCount result{tls_index.module};
    // Loader operations stay outside the registry and Tracker mutexes.
    dl_iterate_phdr(countGreenletModules, &result);
    const bool only = result.count == 1 && result.expected_found;
    std::lock_guard<std::mutex> lock(registry->mutex);
    if (generation != module_generation.load(std::memory_order_acquire)) return false;
    single_module.store(only, std::memory_order_relaxed);
    single_module_generation.store(generation, std::memory_order_release);
    return only;
}

int
copyModuleTls(dl_phdr_info* info, size_t info_size, void* raw)
{
    if (info_size < offsetof(dl_phdr_info, dlpi_tls_data) + sizeof(info->dlpi_tls_data)) return 0;
    auto& result = *static_cast<ModuleTls*>(raw);
    if (result.module != info->dlpi_tls_modid) return 0;
    copyTls(info, result);
    return 1;
}

extern "C" void*
__tls_get_addr(void*);

void
resolveTls(ModuleTls& result)
{
    if (!result.found || !result.module || !result.size || result.data || result.uses_get_addr) return;
    // Static TLS and TLSDESC can leave the loader's soft lookup empty.
    // Resolve outside dl_iterate_phdr and the registry/Tracker locks.
    RecursionGuard guard;
    TlsIndex index{result.module, 0};
    result.data = static_cast<const char*>(__tls_get_addr(&index));
}

void
discoverModule(ModuleTls& result)
{
    dl_iterate_phdr(findModule, &result);
    resolveTls(result);
}
#    else
void
discoverModule(ModuleTls& result)
{
    for (uint32_t i = 0; i < _dyld_image_count(); ++i) {
        const auto* header = _dyld_get_image_header(i);
        if (!header) continue;
        const auto slide = _dyld_get_image_vmaddr_slide(i);
        DynamicInfoTable image(header, slide, [](const char*) { return true; });
        const auto type = image.getSymbolAddress("_PyGreenlet_Type", slide);
        const auto initialize = image.getSymbolAddress("_PyInit__greenlet", slide);
        if (!type && !initialize) continue;
        module_present.store(true, std::memory_order_release);
        if (!setGreenletType(result, type)) continue;
        const auto tls = image.threadLocalStorage(slide);
        if (!tls.size) continue;
        // Reserve zero for an undiscovered module; pthread key zero is valid.
        result.module = static_cast<size_t>(tls.key) + 1;
        result.size = tls.size;
        result.data = static_cast<const char*>(pthread_getspecific(tls.key));
        result.found = true;
        return;
    }
}

bool
isOnlyGreenletModule()
{
    return false;
}
#    endif

struct CachedTls
{
    size_t module{};
    uint64_t generation{};
    const char* data{};
};
MEMRAY_FAST_TLS thread_local CachedTls t_tls;

const char*
currentTls(size_t module, [[maybe_unused]] bool uses_get_addr, bool* found = nullptr)
{
#    ifdef __APPLE__
    if (found) *found = true;
    return static_cast<const char*>(pthread_getspecific(module - 1));
#    else
    const auto generation = module_generation.load(std::memory_order_acquire);
    if (t_tls.module == module && t_tls.generation == generation && t_tls.data) {
        if (found) *found = true;
        return t_tls.data;
    }
    ModuleTls local;
    local.module = module;
    local.uses_get_addr = uses_get_addr;
    dl_iterate_phdr(copyModuleTls, &local);
    resolveTls(local);
    t_tls = {module, generation, local.data};
    if (found) *found = local.found;
    return local.data;
#    endif
}

void
calibrate()
{
    // Read shared metadata briefly, then release the registry before any loader
    // operation. The supported resolver model preserves unused-thread TLS.
    if (calibrated.load(std::memory_order_acquire)) return;
    const auto generation = module_generation.load(std::memory_order_acquire);
    ModuleTls module;
    bool discover;
    {
        std::lock_guard<std::mutex> lock(registry->mutex);
        if (calibrated.load(std::memory_order_relaxed)) return;
        module.module = tls_index.module;
        module.size = tls_size;
        module.type = greenlet_type;
        module.uses_get_addr = tls_uses_get_addr;
        discover = generation != checked_generation.load(std::memory_order_relaxed);
    }
    if (discover) {
        module = {};
        discoverModule(module);
    } else if (module.module) {
        module.data = currentTls(module.module, module.uses_get_addr);
    }

    unsigned matches = 0;
    size_t found_tls = 0, found_main = 0;
    if (module.data) {
        for (size_t offset = 0; offset + sizeof(uintptr_t) <= module.size; offset += alignof(uintptr_t))
        {
            uintptr_t state;
            if (compat::copyReadableMemory(&state, module.data + offset, sizeof(state)) != sizeof(state)
                || state <= 1)
                continue;
            uintptr_t words[16];
            const auto count =
                    compat::copyReadableMemory(words, reinterpret_cast<void*>(state), sizeof(words))
                    / sizeof(uintptr_t);
            for (size_t index = 1; index < count; ++index) {
                GreenletPrefix main, current;
                if (!readGreenlet(words[index - 1], main, true, module.type)
                    || !readGreenlet(words[index], current, false, module.type)
                    || !mainOwnsState(words[index - 1], main.implementation, state))
                {
                    continue;
                }
                ++matches;
                found_tls = offset;
                found_main = (index - 1) * sizeof(uintptr_t);
            }
        }
    }

    bool warn = false;
    {
        std::lock_guard<std::mutex> lock(registry->mutex);
        if (!calibrated.load(std::memory_order_relaxed)
            && generation == module_generation.load(std::memory_order_acquire))
        {
            if (discover) {
                checked_generation.store(generation, std::memory_order_release);
                tls_index.module = module.module;
                tls_size = module.size;
                greenlet_type = module.type;
                tls_uses_get_addr = module.uses_get_addr;
            }
            if (module.module && tls_index.module == module.module && matches == 1) {
                tls_index.offset = found_tls;
                main_offset = found_main;
                t_tls = {module.module, generation, module.data};
                // The release publishes the offsets and TLS model together.
                calibrated.store(true, std::memory_order_release);
            }
            if (module.unsupported && !unsupported_warning) {
                unsupported_warning = true;
                warn = true;
            }
        }
    }
    if (warn) {
        constexpr char message[] =
                "Memray: unsupported native greenlet layout; logical greenlet IDs are unavailable.\n";
        const auto written = write(STDERR_FILENO, message, sizeof(message) - 1);
        (void)written;
    }
}

#endif
}  // namespace

static uintptr_t
identityHash(void* pointer)
{
    uintptr_t value = reinterpret_cast<uintptr_t>(pointer) >> 4;
    value ^= value >> 16;
    return value * uintptr_t{0x9e3779b1};
}

static bool
possiblyRegistered(void* pointer)
{
    const auto hash = identityHash(pointer);
    return identity_filter[(hash >> 6) & 255].load(std::memory_order_acquire)
           & (uint64_t{1} << (hash & 63));
}

static void
markRegistered(void* pointer)
{
    const auto hash = identityHash(pointer);
    identity_filter[(hash >> 6) & 255].fetch_or(uint64_t{1} << (hash & 63), std::memory_order_release);
}

static void
clearIdentities()
{
    // The caller holds the registry mutex at an inactive session boundary.
    identity_generation.fetch_add(1, std::memory_order_release);
    registry->identities.clear();
    for (auto& word : identity_filter)
        word.store(0, std::memory_order_release);
    identities_present.store(false, std::memory_order_release);
}

void
beginTracking()
{
    RecursionGuard guard;
    // Modules can load while the allocator and dlopen hooks are inactive.
    module_generation.fetch_add(1, std::memory_order_release);
    static std::once_flag once;
    std::call_once(once, [] { registry = new Registry; });
#if defined(__linux__) || defined(__APPLE__)
    calibrate();
#endif
    std::lock_guard<std::mutex> lock(registry->mutex);
    clearIdentities();
    active.store(true, std::memory_order_release);
}
void
endTracking()
{
    RecursionGuard guard;
    active.store(false, std::memory_order_release);
    identities_present.store(false, std::memory_order_release);
    if (!registry) return;
    std::lock_guard<std::mutex> lock(registry->mutex);
    clearIdentities();
}
void
markModuleLoaded()
{
    module_generation.fetch_add(1, std::memory_order_release);
}
struct CurrentGreenlet
{
    uintptr_t address{};
    bool absent{};
};

static CurrentGreenlet
currentGreenlet()
{
#if defined(__linux__) || defined(__APPLE__)
    if (!active.load(std::memory_order_acquire) || !registry) {
        return {};
    }
    const bool ready = calibrated.load(std::memory_order_acquire);
    if (!ready) {
        const auto generation = module_generation.load(std::memory_order_acquire);
        const auto checked = checked_generation.load(std::memory_order_acquire);
        if (checked == generation && !module_present.load(std::memory_order_acquire)
            && generation == module_generation.load(std::memory_order_acquire))
        {
            return {0, true};
        }
    }
    // Do not read greenlet TLS after the bound Python thread state is gone.
    if (!python_stack_capture::hasThreadState()) return {};
    if (!ready) {
        RecursionGuard guard;
        calibrate();
        if (!calibrated.load(std::memory_order_acquire)) return {};
    }
    bool module_found = false;
    const char* block = currentTls(tls_index.module, tls_uses_get_addr, &module_found);
    // Only the supported __tls_get_addr model proves that null TLS means no
    // prior greenlet use. Initial-exec and TLSDESC can access a static block
    // while dlpi_tls_data remains null. Recheck null on every capture.
    if (!block) {
        return {0, module_found && tls_uses_get_addr && isOnlyGreenletModule()};
    }
    const uintptr_t state = *reinterpret_cast<const uintptr_t*>(block + tls_index.offset);
    if (state <= 1) return {};
    const uintptr_t main = *reinterpret_cast<uintptr_t*>(state + main_offset);
    const uintptr_t current = *reinterpret_cast<uintptr_t*>(state + main_offset + sizeof(uintptr_t));
    if (!main || !current) return {};
    if (current == main) return {};
    return {current};
#else
    return {};
#endif
}

bool
threadKnownAbsent()
{
#ifdef MEMRAY_WITH_FRAME_MARKERS
    // currentIdentity refreshes this proof before Tracker::s_mutex. No Python
    // or greenlet execution occurs before the corresponding emit.
    return active.load(std::memory_order_acquire) && t_absent_generation
           && t_absent_generation == module_generation.load(std::memory_order_acquire);
#else
    return false;
#endif
}

uintptr_t
currentIdentity()
{
#ifdef MEMRAY_WITH_FRAME_MARKERS
    const auto generation_before = module_generation.load(std::memory_order_acquire);
#endif
    const auto state = currentGreenlet();
#ifdef MEMRAY_WITH_FRAME_MARKERS
    t_absent_generation =
            state.absent && generation_before == module_generation.load(std::memory_order_acquire)
                    ? generation_before
                    : 0;
#endif
    const uintptr_t current = state.address;
    if (!current) return 0;
    void* implementation = reinterpret_cast<GreenletPrefix*>(current)->implementation;
    if (!implementation) return 0;
    const auto generation = identity_generation.load(std::memory_order_acquire);
    if (t_identity.generation == generation && t_identity.implementation == implementation) {
        return t_identity.identity;
    }
    RecursionGuard guard;
    std::lock_guard<std::mutex> lock(registry->mutex);
    auto [entry, inserted] = registry->identities.try_emplace(implementation, 0);
    if (inserted) {
        entry->second = allocateThreadId();
        markRegistered(implementation);
        identities_present.store(true, std::memory_order_release);
    }
    t_identity = {identity_generation.load(std::memory_order_relaxed), implementation, entry->second};
    return entry->second;
}
void
forgetAllocation(void* pointer)
{
    if (!pointer || !active.load(std::memory_order_acquire)
        || !identities_present.load(std::memory_order_acquire) || !registry)
        return;
    // Bits remain set until the registry is empty at a session boundary.
    // False positives take the mutex. A registered address cannot be missed.
    if (!possiblyRegistered(pointer)) return;
    RecursionGuard guard;
    std::lock_guard<std::mutex> lock(registry->mutex);
    const auto found = registry->identities.find(pointer);
    if (found == registry->identities.end()) return;
    identity_generation.fetch_add(1, std::memory_order_release);
    registry->identities.erase(found);
    if (registry->identities.empty()) identities_present.store(false, std::memory_order_release);
}
void
childFork()
{
    RecursionGuard guard;
    if (!registry) return;
#if defined(__linux__) || defined(__APPLE__)
    // Another thread can own or mutate the inherited registry at fork.
    // Do not lock, traverse, or destroy that copy in the child.
    registry = new Registry;
    clearIdentities();
    t_identity = {};
#    ifdef MEMRAY_WITH_FRAME_MARKERS
    t_absent_generation = 0;
#    endif
    t_tls = {};
    single_module_generation.store(0, std::memory_order_release);
    if (!calibrated.load(std::memory_order_acquire)) {
        // A publication can be incomplete in the inherited process image.
        // Discover the child state anew before any TLS read.
        tls_index = {};
        tls_size = 0;
        greenlet_type = nullptr;
        tls_uses_get_addr = false;
        checked_generation.store(0, std::memory_order_release);
        module_generation.fetch_add(1, std::memory_order_release);
    }
#endif
}

}  // namespace memray::tracking_api::greenlet_adapter
