#pragma once

#include <malloc.h>
#include <stdlib.h>

extern "C" {
#ifndef __GLIBC__
static void*
pvalloc(size_t size)
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
}
