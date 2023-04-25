#pragma once

#ifdef __linux__
#    include <malloc.h>
#endif

#include <stdlib.h>

extern "C" {
#ifndef __GLIBC__
static void*
pvalloc [[maybe_unused]] (size_t size)
{
    return NULL;
}
#endif

#if !defined(_ISOC11_SOURCE) && defined(__GLIBC__)
static void*
aligned_alloc(size_t alignment, size_t size)
{
    return NULL;
}
#endif

#ifdef __APPLE__

static void*
memalign [[maybe_unused]] (size_t alignment, size_t size)
{
    return NULL;
}
#endif
}
