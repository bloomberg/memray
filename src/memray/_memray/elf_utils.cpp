#include "elf_utils.h"
#include "logging.h"
#include <cstring>
#include <elf.h>
#include <iostream>
#include <link.h>
#include <string>
#include <sys/mman.h>

namespace memray::elf {
static uintptr_t
stringTableOffset(const char* file_name)
{
    Elf_Ehdr header;
    auto file = std::ifstream(file_name, std::ios::binary | std::ios::in);
    if (!file) {
        memray::LOG(memray::ERROR) << "Failed to open file " << file_name
                                   << " for relocation validation.";
        return 0;
    }
    if (file.read(reinterpret_cast<char*>(&header), sizeof(Elf_Ehdr)).fail()) {
        memray::LOG(memray::ERROR) << "Failed to read ELF header for relocation validation.";
        return 0;
    }

    file.seekg((long)header.e_phoff);

    char phdr[header.e_phentsize * header.e_phnum];
    if (file.read(phdr, header.e_phentsize * header.e_phnum).fail()) {
        memray::LOG(memray::ERROR) << "Failed to read phnum entries for relocation validation.";
        return 0;
    }

    // find dynamic
    Elf_Phdr* dynamicEntry = nullptr;
    for (size_t i = 0; i < header.e_phnum; i++) {
        Elf_Phdr& entry = *((Elf_Phdr*)&phdr[header.e_phentsize * i]);
        if (entry.p_type == PT_DYNAMIC) dynamicEntry = &entry;
    }
    if (dynamicEntry == nullptr) {
        return 0;
    }

    size_t dynamicDataCount = dynamicEntry->p_filesz / sizeof(Elf_Dyn);
    Elf_Dyn dynamicData[dynamicDataCount];
    file.seekg((long)dynamicEntry->p_offset);

    if (file.read(reinterpret_cast<char*>(dynamicData), sizeof(Elf_Dyn) * dynamicDataCount).fail()) {
        memray::LOG(memray::ERROR) << "Failed to read PT_DYNAMIC entries for relocation validation.";
        return {};
    }

    // find strtab
    for (size_t i = 0; i < dynamicDataCount; i++) {
        if (dynamicData[i].d_tag != DT_STRTAB) {
            continue;
        }
        return dynamicData[i].d_un.d_val;
    }
    return 0;
}

bool
dynamicTableNeedsRelocation(const char* file_name, const Addr base, const Dyn* dynamic_section)
{
    // When the base address is 0 we cannot distinguish offsets from virtual addresses.
    if (base == 0) {
        return false;
    }

    static bool resolved = false;
    static bool needs_relocation = false;

    // Check if we already know if this system requires relocations
    if (resolved) {
        return needs_relocation;
    }

    // Get offset of the string table from file
    if (!file_name || file_name[0] == '\0') {
        file_name = "/proc/self/exe";
    }
    uintptr_t string_table_offset = stringTableOffset(file_name);

    // Get address or offset for the string table from the loaded dynamic table

    uintptr_t string_table_addr = 0;
    for (; dynamic_section->d_tag != DT_NULL; ++dynamic_section) {
        if (dynamic_section->d_tag != DT_STRTAB) {
            continue;
        }
        string_table_addr = static_cast<uintptr_t>(dynamic_section->d_un.d_ptr);
    }

    // Check if the string table address is an address or an offset
    needs_relocation = string_table_addr == string_table_offset;
    LOG(DEBUG) << "System needs relocations: " << needs_relocation;

    // Ensure we cache the result, so we don't check every single library
    resolved = true;
    return needs_relocation;
}

SymbolTable::SymbolTable(Addr base, const Dyn* dynamic_section)
: base(base)
, dynamic_section(dynamic_section)
, string_table(base, dynamic_section)
, symbol_table(base, dynamic_section)
{
}

const char*
SymbolTable::getSymbolNameByIndex(size_t index) const
{
    return string_table.table + symbol_table.table[index].st_name;
}

bool
SymbolTable::isDefinedGlobalSymbol(Sym* sym)
{
    unsigned char stb = ELF_ST_BIND(sym->st_info);
    if (stb == STB_GLOBAL || stb == STB_WEAK) {
        return sym->st_shndx != SHN_UNDEF;
    }
    return false;
}

const Dyn*
SymbolTable::findDynByTag(const Dyn* const section_ptr, Sxword tag)
{
    const Dyn* dyn = section_ptr;
    while (dyn->d_tag != DT_NULL) {
        if (dyn->d_tag == tag) {
            return dyn;
        }
        ++dyn;
    }
    return nullptr;
}

uintptr_t
SymbolTable::getSymbolAddress(const char* name) const
{
    uintptr_t result = 0;

    const Dyn* dt_gnu_hash_base = findDynByTag(dynamic_section, DT_GNU_HASH);
    if (dt_gnu_hash_base != nullptr) {
        result = findSymbolByGNUHashTable(name, dt_gnu_hash_base);
    } else {
        // Fallback to DT_HASH if DT_GNU_HASH is not available
        const Dyn* dt_hash_base = findDynByTag(dynamic_section, DT_HASH);
        if (dt_hash_base != nullptr) {
            result = findSymbolByElfHashTable(name, dt_hash_base);
        }
    }

    return result;
}

uintptr_t
SymbolTable::findSymbolByElfHashTable(const char* name, const Dyn* dt_hash_base) const
{
    // See https://www.gabriel.urdhr.fr/2015/09/28/elf-file-format/#hash-tables
    auto* dt_hash = reinterpret_cast<ElfW(Word)*>(base + dt_hash_base->d_un.d_ptr);
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
        auto* sym = reinterpret_cast<Sym*>(symbol_table.table + n);
        auto* sym_name = reinterpret_cast<const char*>(string_table.table + sym->st_name);
        if (isDefinedGlobalSymbol(sym) && strcmp(sym_name, name) == 0) {
            return sym->st_value;
        }
    }

    return 0;
}

uintptr_t
SymbolTable::findSymbolByGNUHashTable(const char* name, const Dyn* dt_gnu_hash_base) const
{
    // Adapted from the holy source of the linker:
    // https://github.com/bminor/glibc/blob/97e42bd482b62d7b74889be11c98b0bbb4059dcd/elf/dl-lookup.c#L355-L569
    // See https://www.gabriel.urdhr.fr/2015/09/28/elf-file-format/#hash-tables
    // and https://sourceware.org/legacy-ml/binutils/2006-10/msg00377.html for more information.

    // DT_GNU_HASH has nothing in common with standard DT_HASH, apart from serving the same purpose.
    // It has its own hashing function, its own layout, it adds restrictions for the symbol table and
    // contains an additional bloom filter to stop lookup for missing symbols early.

    auto* hashtab = reinterpret_cast<ElfW(Word)*>(base + dt_gnu_hash_base->d_un.d_ptr);

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
        if ((namehash | 1) == (hash | 1) && isDefinedGlobalSymbol(sym) && strcmp(sym_name, name) == 0) {
            return sym->st_value;
        }

        // Chain ends with an element with the lowest bit set to 1: end of the chain
        if (hash & 1) {
            break;
        }
        symbol_index++;
    }

    return 0;
}
}  // namespace memray::elf
