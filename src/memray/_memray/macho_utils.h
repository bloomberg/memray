#pragma once

#include <cstring>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <mach-o/nlist.h>
#include <mach/mach.h>
#include <mach/vm_map.h>
#include <mach/vm_region.h>
#include <sys/types.h>
#include <vector>

#include "hooks.h"
#include "linker_shenanigans.h"
#include "logging.h"

#ifndef __APPLE__
#    error "This file can only be compiled in MacOS systems"
#endif

#ifdef __LP64__
typedef struct mach_header_64 mach_header_t;
typedef struct segment_command_64 segment_command_t;
typedef struct section_64 section_t;
typedef struct nlist_64 nlist_t;
#    define ARCH_LC_SEGMENT LC_SEGMENT_64
#else
typedef struct mach_header mach_header_t;
typedef struct segment_command segment_command_t;
typedef struct section section_t;
typedef struct nlist nlist_t;
#    define ARCH_LC_SEGMENT LC_SEGMENT
#endif

#ifndef SEG_DATA_CONST
#    define SEG_DATA_CONST "__DATA_CONST"
#endif

#ifndef SEG_AUTH_CONST
#    define SEG_AUTH_CONST "__AUTH_CONST"
#endif

struct DynamicInfoTable
{
    using segment_filter_t = std::function<bool(const char* segname)>;

    const nlist_t* symbol_table = nullptr;
    const char* string_table = nullptr;
    const uint32_t* dynsym_table = nullptr;
    std::vector<const segment_command_t*> segments;

    explicit DynamicInfoTable(
            const struct mach_header* header,
            uintptr_t slide,
            const segment_filter_t& segment_filter)
    {
        const segment_command_t* linkedit_cmd = nullptr;
        const struct symtab_command* symtab_cmd = nullptr;
        const struct dysymtab_command* dysym_cmd = nullptr;

        const segment_command_t* current_segment_cmd = nullptr;
        uintptr_t current_cmd = reinterpret_cast<uintptr_t>(header) + sizeof(mach_header_t);
        for (uint i = 0; i < header->ncmds; i++, current_cmd += current_segment_cmd->cmdsize) {
            current_segment_cmd = reinterpret_cast<const segment_command_t*>(current_cmd);
            switch (current_segment_cmd->cmd) {
                case ARCH_LC_SEGMENT: {
                    const char* segname = current_segment_cmd->segname;
                    if (strcmp(segname, SEG_LINKEDIT) == 0) {
                        linkedit_cmd = current_segment_cmd;
                    }
                    if (segment_filter(segname)) {
                        segments.emplace_back(current_segment_cmd);
                    }
                } break;
                case LC_SYMTAB:
                    symtab_cmd = reinterpret_cast<const symtab_command*>(current_segment_cmd);
                    break;
                case LC_DYSYMTAB:
                    dysym_cmd = reinterpret_cast<const dysymtab_command*>(current_segment_cmd);
                    break;
            }
        }

        if (!linkedit_cmd || !symtab_cmd || !dysym_cmd) {
            return;
        }
        const auto linkedit_base = slide + linkedit_cmd->vmaddr - linkedit_cmd->fileoff;
        symbol_table = reinterpret_cast<nlist_t*>(linkedit_base + symtab_cmd->symoff);
        string_table = reinterpret_cast<char*>(linkedit_base + symtab_cmd->stroff);
        dynsym_table = reinterpret_cast<uint32_t*>(linkedit_base + dysym_cmd->indirectsymoff);
    }

    explicit operator bool() const
    {
        return symbol_table && string_table && dynsym_table;
    }

    [[nodiscard]] const char* getSymbol(uintptr_t section_offset, unsigned long index) const
    {
        auto index_into_symtable = (dynsym_table + section_offset)[index];
        if (index_into_symtable & (INDIRECT_SYMBOL_ABS | INDIRECT_SYMBOL_LOCAL)) {
            return nullptr;
        }

        uint32_t string_table_offset = symbol_table[index_into_symtable].n_un.n_strx;
        return string_table + string_table_offset;
    }
};
