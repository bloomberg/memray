#include <cstring>
#include <set>
#include <string>
#include <sys/mman.h>
#include <unistd.h>

#include "elf_shenanigans.h"
#include "hooks.h"
#include "logging.h"

#include <link.h>

#if defined __x86_64 || defined __aarch64__
#    define ELF_R_SYM ELF64_R_SYM
#else
#    define ELF_R_SYM ELF32_R_SYM
#endif

namespace pensieve::elf {

/* Utility classes and definitons */

// We use these macros as instructed in the linker header to refer to ELF types independent
// of the native wordsize. In this way, `ElfW(TYPE)' is used in place of `Elf32_TYPE' or `Elf64_TYPE'.
using Addr = ElfW(Addr);
using Dyn = ElfW(Dyn);
using Rel = ElfW(Rel);
using Rela = ElfW(Rela);
using Sym = ElfW(Sym);
using Sxword = ElfW(Sxword);
using Xword = ElfW(Xword);

template<typename T, Sxword AddrTag, Sxword SizeTag>
struct DynamicInfoTable
{
    T* table = nullptr;
    elf::Xword size = {};

    explicit DynamicInfoTable(const Dyn* dynamic_section)
    {
        // Obtain the table address and the size from the tags in the dynamic section
        for (; dynamic_section->d_tag != DT_NULL; ++dynamic_section) {
            if (dynamic_section->d_tag == AddrTag) {
                table = reinterpret_cast<T*>(dynamic_section->d_un.d_ptr);
            } else if (dynamic_section->d_tag == SizeTag) {
                size = dynamic_section->d_un.d_val;
            }
        }
    }

    T* begin() const noexcept
    {
        return table;
    }

    T* end() const noexcept
    {
        return table + size / sizeof(T);
    }
};

using RelTable = DynamicInfoTable<elf::Rel, DT_REL, DT_RELSZ>;
using RelaTable = DynamicInfoTable<elf::Rela, DT_RELA, DT_RELASZ>;
using JmprelTable = DynamicInfoTable<elf::Rela, DT_JMPREL, DT_PLTRELSZ>;

struct SymbolTable
{
    DynamicInfoTable<const char, DT_STRTAB, DT_STRSZ> string_table;
    DynamicInfoTable<elf::Sym, DT_SYMTAB, DT_SYMENT> symbol_table;

    explicit SymbolTable(const Dyn* dynamic_section)
    : string_table(dynamic_section)
    , symbol_table(dynamic_section){};

    const char* get_symbol(size_t index) const
    {
        return string_table.table + symbol_table.table[index].st_name;
    }
};

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
    // Make sure that we can read and write to the page where the address that we are trying to patch;
    if (unprotect_page(addr) < 0) {
        LOG(WARNING) << "Could not prepare the memory page for symbol " << symname << " for patching";
    }

    // Patch the address with the new function or the original one depending on the value of
    // *restore_original*.
    auto typedAddr = reinterpret_cast<typename Hook::signature_t*>(addr);
    *typedAddr = restore_original ? hook.original : intercept;

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
        const char* symname = symbols.get_symbol(index);
        auto symbol_addr = relocation.r_offset + base_addr;
#define TRY_HOOK(hookname)                                                                              \
    if (strcmp(hooks::hookname.symbol, symname) == 0) {                                                 \
        patch_symbol(hooks::hookname, &intercept::hookname, symname, symbol_addr, restore_original);    \
        continue;                                                                                       \
    }
        TRY_HOOK(malloc);
        TRY_HOOK(free);
        TRY_HOOK(calloc);
        TRY_HOOK(realloc);
        TRY_HOOK(posix_memalign);
        TRY_HOOK(memalign);
        TRY_HOOK(valloc);
        TRY_HOOK(pvalloc);
        TRY_HOOK(dlopen);
        TRY_HOOK(dlclose);
        TRY_HOOK(mmap);
        TRY_HOOK(mmap64);
        TRY_HOOK(munmap);
    }
#undef TRY_HOOK
}

static void
patch_symbols(const Dyn* dyn_info_struct, const Addr base, bool restore_original) noexcept
{
    SymbolTable symbols(dyn_info_struct);

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
    RelTable rels_relocations_table(dyn_info_struct);
    overwrite_elf_table(rels_relocations_table, symbols, base, restore_original);

    LOG(DEBUG) << "Patching symbols with RELAS relocation type";
    RelaTable relas_relocations_table(dyn_info_struct);
    overwrite_elf_table(relas_relocations_table, symbols, base, restore_original);

    LOG(DEBUG) << "Patching symbols with JMPRELS relocation type";
    JmprelTable jmprels_relocations_table(dyn_info_struct);
    overwrite_elf_table(jmprels_relocations_table, symbols, base, restore_original);
}

static int
phdrs_callback(dl_phdr_info* info, [[maybe_unused]] size_t size, void* data) noexcept
{
    static std::set<std::string> patched;
    if (patched.find(info->dlpi_name) != patched.end()) {
        return 0;
    }
    patched.insert(info->dlpi_name);

    bool restore_original = *reinterpret_cast<bool*>(data);

    if (strstr(info->dlpi_name, "/ld-linux")) {
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
        patch_symbols(dyn_info_struct, info->dlpi_addr, restore_original);
    }
    return 0;
}

/* Public API functions */

void
overwrite_symbols() noexcept
{
    bool restore_original = false;
    dl_iterate_phdr(&phdrs_callback, (void*)&restore_original);
}

void
restore_symbols() noexcept
{
    bool restore_original = true;
    dl_iterate_phdr(&phdrs_callback, (void*)&restore_original);
}

}  // namespace pensieve::elf
