#pragma once

#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <sys/mman.h>
#include <unistd.h>

#include "logging.h"

#include <elf.h>
#include <link.h>

namespace memray::elf {

#if INTPTR_MAX == INT64_MAX
#    define ELF_R_SYM ELF64_R_SYM
#    if !defined(ELF_ST_BIND)
#        define ELF_ST_BIND ELF64_ST_BIND
#    endif
#    define ELFCLASS_BITS 64
typedef uint64_t bloom_el_t;
#else
#    define ELF_R_SYM ELF32_R_SYM
#    if !defined(ELF_ST_BIND)
#        define ELF_ST_BIND ELF32_ST_BIND
#    endif
#    define ELFCLASS_BITS 32
typedef uint32_t bloom_el_t;
#endif

/* Utility classes and definitions */

// We use these macros as instructed in the linker header to refer to ELF types independent
// of the native wordsize. In this way, `ElfW(TYPE)' is used in place of `Elf32_TYPE' or `Elf64_TYPE'.
using Addr = ElfW(Addr);
using Dyn = ElfW(Dyn);
using Rel = ElfW(Rel);
using Rela = ElfW(Rela);
using Sym = ElfW(Sym);
using Sxword = ElfW(Sxword);
using Xword = ElfW(Xword);
using Elf_Ehdr = ElfW(Ehdr);
using Elf_Phdr = ElfW(Phdr);
using Elf_Dyn = ElfW(Dyn);

template<typename T, Sxword AddrTag, Sxword SizeTag>
struct DynamicInfoTable
{
    T* table = nullptr;
    Xword size = {};

    explicit DynamicInfoTable(const Addr base, const Dyn* dynamic_section)
    {
        // Obtain the table address and the size from the tags in the dynamic section
        for (; dynamic_section->d_tag != DT_NULL; ++dynamic_section) {
            if (dynamic_section->d_tag == AddrTag) {
                table = reinterpret_cast<T*>(base + dynamic_section->d_un.d_ptr);
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

using RelTable = DynamicInfoTable<Rel, DT_REL, DT_RELSZ>;
using RelaTable = DynamicInfoTable<Rela, DT_RELA, DT_RELASZ>;
using JmpRelTable = DynamicInfoTable<Rel, DT_JMPREL, DT_PLTRELSZ>;
using JmpRelaTable = DynamicInfoTable<Rela, DT_JMPREL, DT_PLTRELSZ>;

bool
dynamicTableNeedsRelocation(const char* file_name, const Addr base, const Dyn* dynamic_section);

struct SymbolTable
{
    // Methods
    explicit SymbolTable(Addr base, const Dyn* dynamic_section);
    const char* getSymbolNameByIndex(size_t index) const;
    static bool isDefinedGlobalSymbol(Sym* sym);
    static const Dyn* findDynByTag(const Dyn* const section_ptr, Sxword tag);
    uintptr_t getSymbolAddress(const char* name) const;
    uintptr_t findSymbolByElfHashTable(const char* name, const Dyn* dt_hash_base) const;
    uintptr_t findSymbolByGNUHashTable(const char* name, const Dyn* dt_gnu_hash_base) const;

    // Data members
    Addr base = 0;
    const Dyn* dynamic_section;
    DynamicInfoTable<const char, DT_STRTAB, DT_STRSZ> string_table;
    DynamicInfoTable<Sym, DT_SYMTAB, DT_SYMENT> symbol_table;
};

}  // namespace memray::elf
