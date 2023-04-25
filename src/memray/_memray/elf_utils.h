#pragma once

#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <sys/mman.h>
#include <unistd.h>

#include <elf.h>
#include <link.h>

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

template<class T, class U>
T
ensureRelocatedAddress(const Addr base, const U addr)
{
    // Depending on the libc version, some values may be already relocated
    // or not. So we need to check first if the relocation already happened
    // and make it ourselves if that is not the case.
    auto the_addr = reinterpret_cast<Addr>(addr);
    if (the_addr < base) {
        return reinterpret_cast<T>(base + the_addr);
    }
    return reinterpret_cast<T>(the_addr);
}

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
                table = ensureRelocatedAddress<T*>(base, dynamic_section->d_un.d_ptr);
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

struct SymbolTable
{
    Addr base = 0;
    const Dyn* dynamic_section;
    DynamicInfoTable<const char, DT_STRTAB, DT_STRSZ> string_table;
    DynamicInfoTable<Sym, DT_SYMTAB, DT_SYMENT> symbol_table;

    explicit SymbolTable(Addr base, const Dyn* dynamic_section)
    : base(base)
    , dynamic_section(dynamic_section)
    , string_table(base, dynamic_section)
    , symbol_table(base, dynamic_section)
    {
    }

    const char* getSymbolNameByIndex(size_t index) const
    {
        return string_table.table + symbol_table.table[index].st_name;
    }

    static inline bool isDefinedGlobalSymbol(ElfW(Sym) * sym)
    {
        unsigned char stb = ELF_ST_BIND(sym->st_info);
        if (stb == STB_GLOBAL || stb == STB_WEAK) {
            return sym->st_shndx != SHN_UNDEF;
        }
        return false;
    }

    static const ElfW(Dyn) * findDynByTag(const ElfW(Dyn) * const section_ptr, ElfW(Sxword) tag)
    {
        const ElfW(Dyn)* dyn = section_ptr;
        while (dyn->d_tag != DT_NULL) {
            if (dyn->d_tag == tag) {
                return dyn;
            }
            ++dyn;
        }
        return nullptr;
    }

    uintptr_t getSymbolAddress(const char* name) const
    {
        uintptr_t result = 0;

        const ElfW(Dyn)* dt_gnu_hash_base = findDynByTag(dynamic_section, DT_GNU_HASH);
        if (dt_gnu_hash_base != nullptr) {
            result = findSymbolByGNUHashTable(name, dt_gnu_hash_base);
        } else {
            // Fallback to DT_HASH if DT_GNU_HASH is not available
            const ElfW(Dyn)* dt_hash_base = findDynByTag(dynamic_section, DT_HASH);
            if (dt_hash_base != nullptr) {
                result = findSymbolByElfHashTable(name, dt_hash_base);
            }
        }

        return result;
    }

    uintptr_t findSymbolByElfHashTable(const char* name, const ElfW(Dyn) * dt_hash_base) const
    {
        // See https://www.gabriel.urdhr.fr/2015/09/28/elf-file-format/#hash-tables
        auto* dt_hash = ensureRelocatedAddress<ElfW(Word)*>(base, dt_hash_base->d_un.d_ptr);
        size_t nbucket_ = dt_hash[0];
        uint32_t* bucket_ = dt_hash + 2;
        uint32_t* chain_ = bucket_ + nbucket_;

        // This function is adapted from the _dl_elf_hash() function in the linker source:
        // https://github.com/bminor/glibc/blob/97e42bd482b62d7b74889be11c98b0bbb4059dcd/sysdeps/generic/dl-hash.h#L26-L73
        auto elf_hash = [](const uint8_t* name) -> uint32_t {
            uint32_t h = 0, g;
            while (*name) {
                h = (h << 4) + *name++;
                g = h & 0xf0000000;
                h ^= g;
                h ^= g >> 24;
            }
            return h;
        };

        uint32_t hash = elf_hash(reinterpret_cast<const uint8_t*>(name));
        for (uint32_t n = bucket_[hash % nbucket_]; n != 0; n = chain_[n]) {
            auto* sym = ensureRelocatedAddress<ElfW(Sym)*>(base, symbol_table.table + n);
            auto* sym_name = ensureRelocatedAddress<char*>(base, string_table.table + sym->st_name);
            if (isDefinedGlobalSymbol(sym) && strcmp(sym_name, name) == 0) {
                return base + sym->st_value;
            }
        }

        return 0;
    }

    uintptr_t findSymbolByGNUHashTable(const char* name, const ElfW(Dyn) * dt_gnu_hash_base) const
    {
        // Adapted from the holy source of the linker:
        // https://github.com/bminor/glibc/blob/97e42bd482b62d7b74889be11c98b0bbb4059dcd/elf/dl-lookup.c#L355-L569
        // See https://www.gabriel.urdhr.fr/2015/09/28/elf-file-format/#hash-tables
        // and https://sourceware.org/legacy-ml/binutils/2006-10/msg00377.html for more information.

        // DT_GNU_HASH has nothing in common with standard DT_HASH, apart from serving the same purpose.
        // It has its own hashing function, its own layout, it adds restrictions for the symbol table and
        // contains an additional bloom filter to stop lookup for missing symbols early.

        auto* hashtab = ensureRelocatedAddress<ElfW(Word)*>(base, dt_gnu_hash_base->d_un.d_ptr);

        // The hash function is adapted from the dl_new_hash() in the linker source:
        // https://github.com/bminor/glibc/blob/97e42bd482b62d7b74889be11c98b0bbb4059dcd/elf/dl-lookup.c#L572-L579
        auto gnu_hash = [](const uint8_t* name) -> uint32_t {
            uint32_t h = 5381;
            while (*name) {
                h += (h << 5) + *name++;
            }
            return h;
        };

        // A Bloom filter is used by GNU_HASH to make the lookup for missing symbols more efficient.
        // Before doing symbol lookup, we take bloom[(hash / ELFCLASS_BITS) % bloom_size]. If bits hash %
        // ELFCLASS_BITS and (hash >> bloom_shift) % ELFCLASS_BITS are set, then the symbol may or may
        // not be in the hash table but if at least one bit is not set then the symbol is certainly
        // absent from the hash table.
        const bloom_el_t* bloom = reinterpret_cast<bloom_el_t*>(hashtab + 4);
        const uint32_t bloom_size = hashtab[2];
        const uint32_t bloom_shift = hashtab[3];

        const uint32_t namehash = gnu_hash(reinterpret_cast<const uint8_t*>(name));
        bloom_el_t word = bloom[(namehash / ELFCLASS_BITS) % bloom_size];
        bloom_el_t mask = 0 | (bloom_el_t)1 << (namehash % ELFCLASS_BITS)
                          | (bloom_el_t)1 << ((namehash >> bloom_shift) % ELFCLASS_BITS);

        /* If at least one bit is not set, the symbol is surely missing. */
        if ((word & mask) != mask) {
            return 0;
        }

        // Chains in the GNU hash table are contiguous sequences of hashes for symbols with the same
        // index. The last bit in chains' element is discarded and instead used for indicating the
        // chain's end. If it is set then the element is the last one in the chain. Bucket are arrays
        // that hold the indexes of the first symbol in the chains. Symbols in the same buckets are
        // stored linearly. The order of the buckets is implementation dependent.

        const uint32_t nbuckets = hashtab[0];
        const auto* buckets = reinterpret_cast<const uint32_t*>(bloom + bloom_size);
        uint32_t symbol_index = buckets[namehash % nbuckets];
        const uint32_t symbol_offset = hashtab[1];
        if (symbol_index < symbol_offset) {
            return 0;
        }
        const uint32_t* chain = &buckets[nbuckets];

        // Search for the symbol in the chain that we found.
        while (true) {
            auto* sym = symbol_table.table + symbol_index;
            const auto* sym_name = string_table.table + sym->st_name;
            const uint32_t hash = chain[symbol_index - symbol_offset];
            if ((namehash | 1) == (hash | 1) && isDefinedGlobalSymbol(sym)
                && strcmp(sym_name, name) == 0)
            {
                return base + sym->st_value;
            }

            // Chain ends with an element with the lowest bit set to 1: end of the chain
            if (hash & 1) {
                break;
            }
            symbol_index++;
        }

        return 0;
    }
};
