#pragma once

namespace memray::tracking_api::capture_lifetime {

void
activate();
void
deactivate();
void
childFork();

class TlbcReadGuard
{
  public:
    TlbcReadGuard();
    ~TlbcReadGuard();
    TlbcReadGuard(const TlbcReadGuard&) = delete;
    TlbcReadGuard& operator=(const TlbcReadGuard&) = delete;
};

}  // namespace memray::tracking_api::capture_lifetime
