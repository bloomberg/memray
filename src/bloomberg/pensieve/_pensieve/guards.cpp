#include "guards.h"

__attribute__((tls_model("local-dynamic"))) thread_local bool RecursionGuard::isActive = false;
