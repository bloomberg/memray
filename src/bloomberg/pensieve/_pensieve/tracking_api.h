#ifndef _PENSIEVE_TRACKING_API_H
#define _PENSIEVE_TRACKING_API_H

namespace pensieve::api {
void
attach_init();

void
attach_fini();
}  // namespace pensieve::api

namespace pensieve::tracking_api {

void
track_allocation(void* ptr, size_t size, const char* func);

void
track_deallocation(void* ptr, const char* func);

void
invalidate_module_cache();

}  // namespace pensieve::tracking_api

#endif  //_PENSIEVE_TRACKING_API_H
