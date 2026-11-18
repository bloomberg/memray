#pragma once

namespace memray::tracking_api {

class Tracker;

namespace python_stack_capture {

void
initialize();
void
beginTracking(bool native);
bool
hasThreadState();
void
emit(Tracker& tracker);
void
clear(Tracker& tracker);
void
invalidateCodeCache();
void
invalidateMarkers();
void
forgetTlbcCode();

}  // namespace python_stack_capture
}  // namespace memray::tracking_api
