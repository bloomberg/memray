#ifndef _PENSIEVE_ELF_SHENANIGANS_H
#define _PENSIEVE_ELF_SHENANIGANS_H

#include <set>
#include <string>

namespace pensieve::elf {

class SymbolPatcher
{
  private:
    std::set<std::string> symbols;

  public:
    void overwrite_symbols() noexcept;
    void restore_symbols() noexcept;
};
}  // namespace pensieve::elf

#endif  //_PENSIEVE_ELF_SHENANIGANS_H
