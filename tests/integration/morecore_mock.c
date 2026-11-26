#define _GNU_SOURCE

#include <pthread.h>
#include <stdatomic.h>
#include <stddef.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

extern void* __libc_malloc(size_t size);

typedef void* (*morecore_t)(ptrdiff_t);

static pthread_mutex_t allocator_lock = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int allocator_lock_is_held = 0;

void*
malloc(size_t size)
{
    if (!atomic_load_explicit(&allocator_lock_is_held, memory_order_relaxed)) {
        return __libc_malloc(size);
    }

    pthread_mutex_lock(&allocator_lock);
    void* result = __libc_malloc(size);
    pthread_mutex_unlock(&allocator_lock);
    return result;
}

static void*
allocator_morecore(ptrdiff_t increment)
{
    return mmap(
            NULL,
            increment,
            PROT_READ | PROT_WRITE,
            MAP_PRIVATE | MAP_ANONYMOUS,
            -1,
            0);
}

morecore_t __morecore = allocator_morecore;

void
trigger_morecore(void)
{
    atomic_store_explicit(&allocator_lock_is_held, 1, memory_order_relaxed);
    pthread_mutex_lock(&allocator_lock);
    void* mapping = __morecore(4096);
    if (mapping != MAP_FAILED) {
        syscall(SYS_munmap, mapping, 4096);
    }
    pthread_mutex_unlock(&allocator_lock);
    atomic_store_explicit(&allocator_lock_is_held, 0, memory_order_relaxed);
}
