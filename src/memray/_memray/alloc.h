#include <malloc.h>
#include <stdlib.h>

#ifndef __GLIBC__
extern "C" {
void*
pvalloc(size_t size)
{
    return NULL;
}
}
#endif
