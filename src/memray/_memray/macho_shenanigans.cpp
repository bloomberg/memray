#include <cstring>

#include "hooks.h"
#include "linker_shenanigans.h"
#include "logging.h"
#include "macho_utils.h"

#ifndef __APPLE__
#    error "This file can only be compiled in MacOS systems"
#endif

namespace memray::linker {

template<typename Hook>
static void
patch_symbol(
        const Hook& hook,
        typename Hook::signature_t intercept,
        const char* symname,
        void* addr,
        vm_size_t section_size,
        bool restore_original)
{
    kern_return_t err = vm_protect(
            mach_task_self(),
            reinterpret_cast<uintptr_t>(addr),
            section_size,
            0,
            VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY);
    if (err == KERN_SUCCESS) {
        auto typedAddr = reinterpret_cast<typename Hook::signature_t*>(addr);
        *typedAddr = restore_original ? hook.d_original : intercept;
        LOG(DEBUG) << symname << " intercepted!";
    } else {
        LOG(ERROR) << "Failed to patch " << symname;
    }
}

static void
patch_symbols_in_section(
        const section_t* section,
        uintptr_t slide,
        const DynamicInfoTable& dyninfo_table,
        bool restore_original)
{
    auto symbol_addr_table = reinterpret_cast<void**>(slide + section->addr);
    for (unsigned int i = 0; i < section->size / sizeof(void*); i++) {
        const char* symbol_name = dyninfo_table.getSymbol(section->reserved1, i);
        if (!symbol_name || !(symbol_name[0] == '_' || symbol_name[0] == '.') || !symbol_name[1]) {
            continue;
        }
#define FOR_EACH_HOOKED_FUNCTION(hookname)                                                              \
    if (strcmp(hooks::hookname.d_symbol, symbol_name + 1) == 0) {                                       \
        patch_symbol(                                                                                   \
                hooks::hookname,                                                                        \
                &intercept::hookname,                                                                   \
                symbol_name,                                                                            \
                symbol_addr_table + i,                                                                  \
                section->size,                                                                          \
                restore_original);                                                                      \
        continue;                                                                                       \
    }
        MEMRAY_HOOKED_FUNCTIONS
#undef FOR_EACH_HOOKED_FUNCTION
    }
}

static void
patch_symbols_in_shared_object(
        const struct mach_header* header,
        intptr_t slide,
        const char* image_name,
        bool restore_original,
        std::set<std::string>& patched)
{
    if (!restore_original) {
        if (patched.find(image_name) != patched.end()) {
            // We already patched this library
            return;
        }
        patched.insert(image_name);
    }

    if (strstr(image_name, "memray.cpython") || strstr(image_name, "/dyld")
        || strstr(image_name, "dyld.dylib"))
    {
        LOG(DEBUG) << "Skipping patching symbols for " << image_name;
        return;
    }
    LOG(DEBUG) << "Patching symbols for " << image_name;

    auto segment_filter = [](const char* seg_name) {
        return strcmp(seg_name, SEG_DATA) == 0 || strcmp(seg_name, SEG_DATA_CONST) == 0
               || strcmp(seg_name, SEG_AUTH_CONST) == 0;
    };

    DynamicInfoTable dyninfo_table(header, slide, segment_filter);
    if (!dyninfo_table) {
        LOG(DEBUG) << "Could not construct dynamic information table" << image_name;
        return;
    }

    LOG(DEBUG) << "Found " << dyninfo_table.segments.size() << " data segments";

    for (const auto& segment_cmd : dyninfo_table.segments) {
        const auto current_seg = reinterpret_cast<uintptr_t>(segment_cmd);
        auto section_head = reinterpret_cast<const section_t*>(current_seg + sizeof(segment_command_t));
        LOG(DEBUG) << "Considering segment " << segment_cmd->segname;
        for (size_t i = 0; i < segment_cmd->nsects; i++) {
            const section_t* section = section_head + i;
            unsigned int section_type = section->flags & SECTION_TYPE;
            if (section_type != S_LAZY_SYMBOL_POINTERS && section_type != S_NON_LAZY_SYMBOL_POINTERS) {
                LOG(DEBUG) << "Skipping section" << i << " (" << section->segname << ")";
                continue;
            }
            LOG(DEBUG) << "Patching section number " << i << " (" << section->segname << ")";
            patch_symbols_in_section(section, slide, dyninfo_table, restore_original);
        }
    }
}

static void
patch_symbols_in_all_shared_objects(bool restore_original, std::set<std::string>& patched)
{
    if (restore_original) {
        patched.clear();
    }
    uint32_t c = _dyld_image_count();
    for (uint32_t i = 0; i < c; i++) {
        const struct mach_header* header = _dyld_get_image_header(i);
        intptr_t slide = _dyld_get_image_vmaddr_slide(i);
        const char* image_name = _dyld_get_image_name(i);
        patch_symbols_in_shared_object(header, slide, image_name, restore_original, patched);
    }
}

/* Public API functions */

void
SymbolPatcher::overwrite_symbols() noexcept
{
    patch_symbols_in_all_shared_objects(false, symbols);
}

void
SymbolPatcher::restore_symbols() noexcept
{
    patch_symbols_in_all_shared_objects(true, symbols);
}

}  // namespace memray::linker
