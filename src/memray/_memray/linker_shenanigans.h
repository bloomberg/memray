#pragma once

#include <set>
#include <string>

namespace memray::linker {

class SymbolPatcher
{
  private:
    std::set<std::string> symbols;

  public:
    void overwrite_symbols() noexcept;
    void restore_symbols() noexcept;
};
}  // namespace memray::linker
