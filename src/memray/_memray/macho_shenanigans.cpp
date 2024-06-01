#include <cstring>

#include "hooks.h"
#include "linker_shenanigans.h"
#include "logging.h"
#include "macho_utils.h"
#include <iomanip>

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
        bool restore_original)
{
    kern_return_t err = vm_protect(
            mach_task_self(),
            reinterpret_cast<uintptr_t>(addr),
            sizeof(void*),
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
    if (strcmp(MEMRAY_ORIG(hookname).d_symbol, symbol_name + 1) == 0) {                                 \
        LOG(DEBUG) << "Patching " << symbol_name << " symbol pointer at " << std::hex << std::showbase  \
                   << *(symbol_addr_table + i) << " for relocation entry " << (symbol_addr_table + i);  \
        patch_symbol(                                                                                   \
                MEMRAY_ORIG(hookname),                                                                  \
                &intercept::hookname,                                                                   \
                symbol_name,                                                                            \
                symbol_addr_table + i,                                                                  \
                restore_original);                                                                      \
        continue;                                                                                       \
    }
        MEMRAY_HOOKED_FUNCTIONS
#undef FOR_EACH_HOOKED_FUNCTION
    }
}

static uint64_t
lazy_pointer_from_stub(uint64_t vaddr)
{
    // We messed with dark forces and we offended the macOS gods and now it is
    // time to pay the price in blood. This function analyzes the machine code
    // of a PLT entry in the __stubs or __auth_stubs section of a shared
    // library that is part of the shared cache and returns the address of the
    // GOT entry that contains the address of the symbol we are looking for.
    // Unfortunately doing this is as crazy as it sounds.

#if defined(__arm64__)
    // For ARM64 architecture, each PLT entry has the following format:
    //
    //   adrp   x17, GOT_OFFSET_IN_PAGES
    //   add    x17, x17, OFFSET_IN_GOT
    //   ldr    x16, [x17]
    //   braa   x16, x17
    //
    // This means that the address of the GOT entry can be calculated as:
    //
    //   addr_of_page(%rip) + page_size() * GOT_OFFSET_IN_PAGES + OFFSET_IN_GOT
    //
    // Where %rip is the instruction pointer of the 1st instruction in the PLT
    // entry, page_size() is 4 KiB, and addr_of_page() is the start address of
    // the 4 KiB page containing a given address.
    //
    // This code parses the machine code of the PLT entry and checks that it
    // matches the expected instructions. If not, it returns 0. Otherwise, it
    // extracts the (signed) GOT_OFFSET_IN_PAGES and (unsigned) OFFSET_IN_GOT
    // values and computes the GOT entry address from them.
    //
    // Relevant documentation:
    // https://developer.arm.com/documentation/ddi0596/2021-12/Base-Instructions/ADRP--Form-PC-relative-address-to-4KB-page-
    // https://developer.arm.com/documentation/ddi0596/2021-12/Base-Instructions/ADD--immediate---Add--immediate--
    // https://developer.arm.com/documentation/ddi0596/2021-12/Base-Instructions/ADDS--immediate---Add--immediate---setting-flags-

    auto instructions = reinterpret_cast<const uint32_t*>(vaddr);

    // Ensure the 1st instruction is an adrp.
    const uint32_t adrp = instructions[0];
    constexpr uint32_t ADRP_MASK = 0x9F000000;
    constexpr uint32_t ADRP_INSTRUCTION = 0x90000000;
    if ((adrp & ADRP_MASK) != ADRP_INSTRUCTION) {
        LOG(DEBUG) << "1st stub instruction is not adrp: " << std::hex << std::setw(8)
                   << std::setfill('0') << (adrp & ADRP_MASK) << " != " << ADRP_INSTRUCTION;
        return 0;
    }

    // Ensure the 2nd instruction is an ADD or ADDS immediate without shift.
    const uint32_t add = instructions[1];
    constexpr uint32_t ADD_MASK = 0xDFC00000;
    constexpr uint32_t ADD_INSTRUCTION = 0x91000000;
    if ((add & ADD_MASK) != ADD_INSTRUCTION) {
        LOG(DEBUG) << "2nd stub instruction is not a 64-bit add immediate: " << std::hex << std::setw(8)
                   << std::setfill('0') << (add & ADD_MASK) << " != " << ADD_INSTRUCTION;
        return 0;
    }

    // Extract the argument from the adrp instruction. It's in 2 pieces.
    // The low 2 value bits are in instruction bits 30-29, inclusive.
    // The high 19 value bits are in instruction bits 23-5, inclusive.
    constexpr uint32_t ADRP_NUM_LO_BITS = 2;
    constexpr uint32_t ADRP_NUM_HI_BITS = 19;
    constexpr uint32_t ADRP_LOWEST_LO_BIT = 29;
    constexpr uint32_t ADRP_LOWEST_HI_BIT = 5;
    constexpr uint32_t ADRP_ARG_LO_MASK = ((1 << ADRP_NUM_LO_BITS) - 1) << ADRP_LOWEST_LO_BIT;
    constexpr uint32_t ADRP_ARG_HI_MASK = ((1 << ADRP_NUM_HI_BITS) - 1) << ADRP_LOWEST_HI_BIT;

    // The constants above show our work. These are the computed masks.
    static_assert(ADRP_ARG_HI_MASK == 0x00FFFFE0);
    static_assert(ADRP_ARG_LO_MASK == 0x60000000);

    // Stitch the two pieces together to find the argument's value.
    int32_t adrp_arg = ((adrp & ADRP_ARG_LO_MASK) >> ADRP_LOWEST_LO_BIT)
                       | ((adrp & ADRP_ARG_HI_MASK) >> (ADRP_LOWEST_HI_BIT - ADRP_NUM_LO_BITS));

    // If the highest bit of the argument is 1 then the value is negative,
    // and we need to sign-extend it by prepending 11 (32 - 19 - 2) 1 bits.
    constexpr uint32_t ADRP_ARG_HIGHEST_BIT_MASK = 1 << (ADRP_LOWEST_HI_BIT + ADRP_NUM_HI_BITS - 1);
    static_assert(ADRP_ARG_HIGHEST_BIT_MASK == 0x00800000);

    if (adrp & ADRP_ARG_HIGHEST_BIT_MASK) {
        LOG(DEBUG) << "sign-extending negative adrp immediate";
        adrp_arg |= 0xFFE00000;
    }

    // Extract the argument from the add instruction. This is easier.
    // It's the 12 bits immediately above the 10 lowest bits.
    constexpr uint32_t ADD_ARG_NUM_BITS = 12;
    constexpr uint32_t ADD_ARG_LOWEST_BIT = 10;
    constexpr uint32_t ADD_ARG_MASK = ((1 << ADD_ARG_NUM_BITS) - 1) << ADD_ARG_LOWEST_BIT;
    static_assert(ADD_ARG_MASK == 0x003ffc00);

    const uint32_t add_arg = (add & ADD_ARG_MASK) >> ADD_ARG_LOWEST_BIT;

    // Compute the final address: find the index of the 4 KiB page containing
    // vaddr, add adrp_arg pages, convert back to a virtual memory address,
    // and add the add_arg offset.
    static_assert(1 << 12 == 4 * 1024);
    return (((vaddr >> 12) + adrp_arg) << 12) + add_arg;

#elif defined(__x86_64__)
    // For x86_64 architecture, each PLT entry has the following format:
    //
    //   jmpq   *OFFSET(%rip)
    //
    // This means that the address of the GOT entry can be calculated as:
    //
    //   %rip + OFFSET
    //
    // Where %rip is the address of the 1st instruction after the jmpq.
    // In other words, it's the address of the jmpq plus 6 bytes, because
    // the jmpq instruction is 6 bytes long.
    //
    // This code parses the machine code of the PLT entry and checks that it
    // matches the expected instruction. If not, it returns 0. Otherwise, it
    // extracts the (signed) OFFSET and computes the GOT entry address.
    //
    // Relevant documentation:
    // https://www.felixcloutier.com/x86/jmp

    // Check if the instruction is a jump.
    const auto instruction = *reinterpret_cast<const uint16_t*>(vaddr);
    constexpr uint16_t JMP_INSTRUCTION = 0x25ff;
    if (instruction != JMP_INSTRUCTION) {
        LOG(DEBUG) << "1st stub instruction isn't jmp: " << std::hex << std::setw(4) << std::setfill('0')
                   << instruction << " != " << JMP_INSTRUCTION;
        return 0;
    }

    // Computing the final address by combining the PLT entry address and the offset
    const auto offset = *reinterpret_cast<const int32_t*>(vaddr + 2);
    const uint64_t rip = vaddr + sizeof(instruction) + sizeof(offset);
    return rip + offset;

#else
    LOG(ERROR) << "Unknown arch to compute address from stub at " << std::hex << std::showbase << vaddr;
    return 0;
#endif
}

static void
patch_stubs(
        const section_t* section,
        uintptr_t slide,
        const DynamicInfoTable& dyninfo_table,
        bool restore_original)
{
    auto symbol_addr_table = reinterpret_cast<char*>(slide + section->addr);
    size_t element_size = section->reserved2;
    if (element_size == 0) {
        LOG(DEBUG) << "Cannot patch stubs because element size is 0";
        return;
    }
    for (unsigned int i = 0; i < section->size / element_size; i++) {
        const char* symbol_name = dyninfo_table.getSymbol(section->reserved1, i);
        if (!symbol_name || !(symbol_name[0] == '_' || symbol_name[0] == '.') || !symbol_name[1]) {
            continue;
        }
        auto stub_addr = reinterpret_cast<uint64_t>(symbol_addr_table + i * element_size);
#define FOR_EACH_HOOKED_FUNCTION(hookname)                                                              \
    if (strcmp(MEMRAY_ORIG(hookname).d_symbol, symbol_name + 1) == 0) {                                 \
        LOG(DEBUG) << "Extracting symbol address for " << symbol_name << " from stub function at "      \
                   << std::hex << std::showbase << stub_addr;                                           \
        void* symbol_addr = reinterpret_cast<void*>(lazy_pointer_from_stub(stub_addr));                 \
        if (!symbol_addr) {                                                                             \
            LOG(DEBUG) << "Symbol address could not be identified";                                     \
            continue;                                                                                   \
        }                                                                                               \
        LOG(DEBUG) << "Patching " << symbol_name << " pointer at address " << std::hex << std::showbase \
                   << symbol_addr;                                                                      \
        patch_symbol(                                                                                   \
                MEMRAY_ORIG(hookname),                                                                  \
                &intercept::hookname,                                                                   \
                symbol_name,                                                                            \
                symbol_addr,                                                                            \
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
               || strcmp(seg_name, SEG_AUTH_CONST) == 0 || strcmp(seg_name, SEG_TEXT) == 0;
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
            LOG(DEBUG) << "Considering section " << i << " (" << section->segname << ":"
                       << section->sectname << ")";

            // dlopen with null and check for _dyld_shared_cache_contains_path but do it only
            // once with std::once_flag
            static std::function<bool(const char*)> dyld_shared_cache_contains_path;
            static std::once_flag _dyld_shared_cache_check_flag;
            std::call_once(_dyld_shared_cache_check_flag, [&]() {
                void* handle = dlopen(nullptr, RTLD_LAZY);
                dyld_shared_cache_contains_path =
                        (bool (*)(const char*))(dlsym(handle, "_dyld_shared_cache_contains_path"));
                dlclose(handle);
            });

            if (dyld_shared_cache_contains_path && _dyld_shared_cache_contains_path(image_name)
                && strcmp(section->segname, SEG_TEXT) == 0)
            {
                // Shared libraries that are part of the shared cache will have the symbols we are
                // looking for in the __stubs/__auth_stubs PLT section pointing to a GOT that we cannot
                // access checking data sections. This means that the only way to get the GOT location
                // is by analyzing the PLT stubs directly using dark rituals and black magic.
                if (strcmp(section->sectname, "__auth_stubs") != 0
                    && strcmp(section->sectname, "__stubs") != 0)
                {
                    LOG(DEBUG) << "Skipping section " << i << " (" << section->segname << ":"
                               << section->sectname << ")";
                    continue;
                }
                // MacOS has some memory interposition libraries that can make us crash (via
                // stackoverflow when initializing TLS variables) if we patch them. This is because these
                // libraries interact in a way we cannot avoid with libdyld, which in turn sets the TLS
                // on first init.
                if (strstr(image_name, "MallocStackLogging")) {
                    LOG(DEBUG) << "Skipping section " << i << " (" << section->segname << ":"
                               << section->sectname << ")";
                    continue;
                }
                LOG(DEBUG) << "Patching section " << i << " (" << section->segname << ":"
                           << section->sectname << ")";
                patch_stubs(section, slide, dyninfo_table, restore_original);
            } else {
                if (section_type != S_LAZY_SYMBOL_POINTERS && section_type != S_NON_LAZY_SYMBOL_POINTERS)
                {
                    LOG(DEBUG) << "Skipping section " << i << " (" << section->segname << ":"
                               << section->sectname << ")";
                    continue;
                }
                LOG(DEBUG) << "Patching section " << i << " (" << section->segname << ":"
                           << section->sectname << ")";
                patch_symbols_in_section(section, slide, dyninfo_table, restore_original);
            }
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
        if (strstr(image_name, "libdyld.dylib") || strstr(image_name, "/usr/lib/system/")) {
            LOG(DEBUG) << "Skipping patching image: " << image_name;
            continue;
        }
        LOG(DEBUG) << "Patching image: " << image_name;
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
