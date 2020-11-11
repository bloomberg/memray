#include "guards.h"

thread_local bool RecursionGuard::isActive = false;
