#include <cstring>
#include <set>
#include <string>
#include <sys/mman.h>
#include <unistd.h>

#include "elf_utils.h"
#include <link.h>

#include "hooks.h"
#include "linker_shenanigans.h"
#include "logging.h"

namespace {

/* Private struct to pass data to phdrs_callback. */
struct elf_patcher_context_t
{
    bool restore_original;
    std::set<std::string> patched;
};

}  // namespace

namespace memray::linker {

/* Patching functions */

static inline int
unprotect_page(Addr addr)
{
    static size_t page_len = getpagesize();
    auto memory_page = reinterpret_cast<void*>(addr & ~(page_len - 1));
    return mprotect(memory_page, page_len, PROT_READ | PROT_WRITE);
}

template<typename Hook>
static void
patch_symbol(
        const Hook& hook,
        typename Hook::signature_t intercept,
        const char* symname,
        Addr addr,
        bool restore_original)
{
    // Make sure that we can read and write to the page where the address that we are trying to
    // patch;
    if (unprotect_page(addr) < 0) {
        LOG(WARNING) << "Could not prepare the memory page for symbol " << symname << " for patching";
    }

    // Patch the address with the new function or the original one depending on the value of
    // *restore_original*.
    auto typedAddr = reinterpret_cast<typename Hook::signature_t*>(addr);
    *typedAddr = restore_original ? hook.d_original : intercept;

    LOG(DEBUG) << symname << " intercepted!";
}

template<typename Table>
static void
overwrite_elf_table(
        const Table& table,
        const SymbolTable& symbols,
        const Addr base_addr,
        bool restore_original) noexcept
{
    for (const auto& relocation : table) {
        /* Every element contains relocation entries that look like this:
         *
         *   typedef struct
         *   {
         *       Elf_Addr	r_offset;		// Address
         *       Elf_Word	r_info;			// Relocation type and symbol index
         *   } Elf_Rel;
         *
         * We are interested mainly on the r_info field, which is a word
         * containing an index in the symbol table and also the type of the
         * relocation. With the index and the symbol table (and the string
         * table) we can resolve the symbol name.
         */
        const auto index = ELF_R_SYM(relocation.r_info);
        const char* symname = symbols.getSymbolNameByIndex(index);
        auto symbol_addr = relocation.r_offset + base_addr;
#define FOR_EACH_HOOKED_FUNCTION(hookname)                                                              \
    if (strcmp(MEMRAY_ORIG(hookname).d_symbol, symname) == 0) {                                         \
        patch_symbol(                                                                                   \
                MEMRAY_ORIG(hookname),                                                                  \
                &intercept::hookname,                                                                   \
                symname,                                                                                \
                symbol_addr,                                                                            \
                restore_original);                                                                      \
        continue;                                                                                       \
    }
        MEMRAY_HOOKED_FUNCTIONS
    }
#undef FOR_EACH_HOOKED_FUNCTION
}

static Sxword
get_jump_table_type(const Dyn* dynamic_section)
{
    // The PLT/Jump table can have different entry types depending on the
    // phase of the moon, the position of the planets, the current weather
    // and other unpredictable stuff. Normally x86_64 uses RELA entries,
    // and x86 uses REL entries. But sometimes it doesn't happen, so we need
    // to check the DT_PLTREL tag to see which one we should use at runtime.
    for (; dynamic_section->d_tag != DT_NULL; ++dynamic_section) {
        if (dynamic_section->d_tag != DT_PLTREL) {
            continue;
        }
        return dynamic_section->d_un.d_val;
    }
    return 0;
}

static void
patch_symbols(const Dyn* dyn_info_struct, const Addr base, bool restore_original) noexcept
{
    SymbolTable symbols(base, dyn_info_struct);

    /* There are three collections of symbols we want to override:
     *
     *    - Relocation table containing entries with implicit addends (RelTable)
     *    - Relocation table containing entries with explicit addends (RelaTable)
     *    - Relocations involving the procedure linkage table (JmprelTable)
     *
     * We do not need to treat differently these symbols because the linker has
     * already done its job and the structures are abstracted for us. At the end
     * of the day, these constructs provide the location of the resolved function
     * and our job is just overwrite that value.
     *
     */

    LOG(DEBUG) << "Patching symbols with RELS relocation type";
    RelTable rels_relocations_table(base, dyn_info_struct);
    overwrite_elf_table(rels_relocations_table, symbols, base, restore_original);

    LOG(DEBUG) << "Patching symbols with RELAS relocation type";
    RelaTable relas_relocations_table(base, dyn_info_struct);
    overwrite_elf_table(relas_relocations_table, symbols, base, restore_original);

    LOG(DEBUG) << "Patching symbols with JMPRELS relocation type";
    switch (get_jump_table_type(dyn_info_struct)) {
        case DT_REL: {
            JmpRelTable jmp_relocations_table(base, dyn_info_struct);
            overwrite_elf_table(jmp_relocations_table, symbols, base, restore_original);
        } break;
        case DT_RELA: {
            JmpRelaTable jmp_relocations_table(base, dyn_info_struct);
            overwrite_elf_table(jmp_relocations_table, symbols, base, restore_original);
        } break;
        default: {
            LOG(DEBUG) << "Unknown JMPRELS relocation table type";
        } break;
    }
}

static int
phdrs_callback(dl_phdr_info* info, [[maybe_unused]] size_t size, void* data) noexcept
{
    elf_patcher_context_t context = *reinterpret_cast<elf_patcher_context_t*>(data);
    std::set<std::string> patched = context.patched;

    if (context.restore_original) {
        patched.clear();
    } else {
        if (patched.find(info->dlpi_name) != patched.end()) {
            return 0;
        }
        patched.insert(info->dlpi_name);
    }

    if (strstr(info->dlpi_name, "/ld-linux") || strstr(info->dlpi_name, "/ld-musl")
        || strstr(info->dlpi_name, "linux-vdso.so.1"))
    {
        // Avoid chaos by not overwriting the symbols in the linker.
        // TODO: Don't override the symbols in our shared library!
        return 0;
    }

    LOG(INFO) << "Patching symbols for " << info->dlpi_name;

    for (auto phdr = info->dlpi_phdr, end = phdr + info->dlpi_phnum; phdr != end; ++phdr) {
        // The information of all the symbols that we want to overwrite are in the PT_DYNAMIC program
        // header, that contains the dynamic linking information.
        if (phdr->p_type != PT_DYNAMIC) {
            continue;
        }
        const auto* dyn_info_struct = reinterpret_cast<const Dyn*>(phdr->p_vaddr + info->dlpi_addr);
        patch_symbols(dyn_info_struct, info->dlpi_addr, context.restore_original);
    }
    return 0;
}

/* Public API functions */

void
SymbolPatcher::overwrite_symbols() noexcept
{
    elf_patcher_context_t context{false, symbols};
    dl_iterate_phdr(&phdrs_callback, (void*)&context);
}

void
SymbolPatcher::restore_symbols() noexcept
{
    elf_patcher_context_t context{true, symbols};
    dl_iterate_phdr(&phdrs_callback, (void*)&context);
}

}  // namespace memray::linker
