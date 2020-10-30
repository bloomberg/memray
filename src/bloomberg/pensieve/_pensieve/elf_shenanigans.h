#ifndef _PENSIEVE_ELF_SHENANIGANS_H
#define _PENSIEVE_ELF_SHENANIGANS_H

namespace pensieve::elf {
void
overwrite_symbols() noexcept;
void
restore_symbols() noexcept;
}  // namespace pensieve::elf

#endif  //_PENSIEVE_ELF_SHENANIGANS_H
