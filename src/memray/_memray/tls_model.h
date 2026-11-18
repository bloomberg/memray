#pragma once
#include "elf_utils.h"

namespace memray::tracking_api::greenlet_adapter {

inline bool
moduleContains(const dl_phdr_info* info, uintptr_t address, size_t size)
{
    for (ElfW(Half) index = 0; index < info->dlpi_phnum; ++index) {
        const auto& segment = info->dlpi_phdr[index];
        const auto start = info->dlpi_addr + segment.p_vaddr;
        if (segment.p_type == PT_LOAD && size <= segment.p_memsz && address >= start
            && address - start <= segment.p_memsz - size)
        {
            return true;
        }
    }
    return false;
}

inline bool
usesGetAddrTls(const dl_phdr_info* info)
{
#if defined(__linux__) && defined(__x86_64__)
    const Dyn* dynamic = nullptr;
    size_t dynamic_size = 0;
    for (ElfW(Half) i = 0; i < info->dlpi_phnum; ++i) {
        if (info->dlpi_phdr[i].p_type == PT_DYNAMIC) {
            dynamic = reinterpret_cast<const Dyn*>(info->dlpi_addr + info->dlpi_phdr[i].p_vaddr);
            dynamic_size = info->dlpi_phdr[i].p_memsz;
        }
    }
    if (!dynamic || !moduleContains(info, reinterpret_cast<uintptr_t>(dynamic), dynamic_size))
        return false;
    bool terminated = false;
    for (size_t i = 0; i < dynamic_size / sizeof(Dyn); ++i) {
        const auto& tag = dynamic[i];
        if (tag.d_tag == DT_NULL) {
            terminated = true;
            break;
        }
        if ((tag.d_tag == DT_FLAGS && (tag.d_un.d_val & DF_STATIC_TLS)) || tag.d_tag == DT_TLSDESC_PLT
            || tag.d_tag == DT_TLSDESC_GOT || (tag.d_tag == DT_RELSZ && tag.d_un.d_val)
            || (tag.d_tag == DT_RELAENT && tag.d_un.d_val != sizeof(Rela))
            || (tag.d_tag == DT_SYMENT && tag.d_un.d_val != sizeof(Sym))
            || (tag.d_tag == DT_PLTREL && tag.d_un.d_val != DT_RELA))
            return false;
    }
    if (!terminated) return false;
    SymbolTable symbols(info->dlpi_addr, dynamic);
    if (!symbols.symbol_table.table || !symbols.string_table.table
        || !moduleContains(
                info,
                reinterpret_cast<uintptr_t>(symbols.string_table.table),
                symbols.string_table.size))
        return false;
    bool own_module = false;
    bool resolver_call = false;
    const auto inspect = [&](const Rela* table, size_t size) {
        if (!size) return true;
        if (!table || size % sizeof(Rela)
            || !moduleContains(info, reinterpret_cast<uintptr_t>(table), size))
            return false;
        for (size_t i = 0; i < size / sizeof(Rela); ++i) {
            const auto type = ELF64_R_TYPE(table[i].r_info);
            const auto symbol_index = ELF64_R_SYM(table[i].r_info);
            if (type == R_X86_64_TPOFF64 || type == R_X86_64_TPOFF32 || type == R_X86_64_GOTTPOFF
                || type == R_X86_64_TLSDESC || type == R_X86_64_TLSDESC_CALL
                || type == R_X86_64_GOTPC32_TLSDESC)
                return false;
            if (type == R_X86_64_DTPMOD64 && symbol_index == 0) own_module = true;
            if (type != R_X86_64_JUMP_SLOT && type != R_X86_64_GLOB_DAT) continue;
            const auto* symbol = symbols.symbol_table.table + symbol_index;
            if (!moduleContains(info, reinterpret_cast<uintptr_t>(symbol), sizeof(Sym))) return false;
            constexpr char resolver[] = "__tls_get_addr";
            if (symbol->st_shndx == SHN_UNDEF && symbol->st_name <= symbols.string_table.size
                && sizeof(resolver) <= symbols.string_table.size - symbol->st_name
                && memcmp(symbols.string_table.table + symbol->st_name, resolver, sizeof(resolver)) == 0)
                resolver_call = true;
        }
        return true;
    };
    const RelaTable relocations(info->dlpi_addr, dynamic);
    const JmpRelaTable calls(info->dlpi_addr, dynamic);
    return inspect(relocations.table, relocations.size) && inspect(calls.table, calls.size) && own_module
           && resolver_call;
#else
    (void)info;
    return false;
#endif
}

}  // namespace memray::tracking_api::greenlet_adapter
