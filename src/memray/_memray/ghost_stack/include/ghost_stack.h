/**
 * GhostStack - Fast Stack Unwinding via Shadow Stacks
 * ====================================================
 *
 * Drop-in replacement for unw_backtrace() that provides O(1) stack capture
 * after initial setup by patching return addresses with trampolines.
 *
 * Basic Usage:
 *
 *     // Initialize once at startup (optional - will auto-init if needed)
 *     ghost_stack_init(NULL);
 *
 *     // Capture stack trace (same signature as unw_backtrace)
 *     void* frames[128];
 *     size_t n = ghost_stack_backtrace(frames, 128);
 *
 *     // When done with this call stack (e.g., returning to event loop)
 *     ghost_stack_reset();
 *
 * Thread Safety:
 *   Each thread has its own shadow stack (thread-local storage).
 *
 * Exception Safety:
 *   C++ exceptions propagate correctly through patched frames.
 */

#ifndef GHOST_STACK_H
#define GHOST_STACK_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Unwinder function signature - same as unw_backtrace().
 * @param buffer   Array to fill with instruction pointers
 * @param size     Maximum frames to capture
 * @return         Number of frames captured
 */
typedef size_t (*ghost_stack_unwinder_t)(void** buffer, size_t size);

/**
 * Initialize GhostStack.
 *
 * @param unwinder  Custom unwinder function, or NULL to use default (unw_backtrace).
 *                  The unwinder is called for initial stack capture; subsequent
 *                  captures use the shadow stack for O(1) performance.
 *
 * Thread-safe. Can be called multiple times (subsequent calls are no-ops).
 * Will be called automatically on first ghost_stack_backtrace() if not
 * explicitly initialized.
 */
void
ghost_stack_init(ghost_stack_unwinder_t unwinder);

/**
 * Capture stack trace - drop-in replacement for unw_backtrace().
 *
 * First call from a given call stack: uses the unwinder + installs trampolines.
 * Subsequent calls from same/deeper stack: O(1) retrieval from shadow stack.
 *
 * @param buffer   Array to fill with return addresses (instruction pointers)
 * @param size     Maximum number of frames to capture
 * @return         Number of frames captured (0 on error)
 */
size_t
ghost_stack_backtrace(void** buffer, size_t size);

/**
 * Reset the shadow stack, restoring all original return addresses.
 *
 * Call this when you want to invalidate the cached stack, e.g.:
 *   - Returning to an event loop
 *   - Before making a call that significantly changes the stack
 *   - On thread exit
 *
 * Safe to call even if no capture has occurred.
 */
void
ghost_stack_reset(void);

/**
 * Clean up thread-local resources.
 *
 * Optional - resources are cleaned up automatically on thread exit.
 * Call explicitly if you want immediate cleanup.
 */
void
ghost_stack_thread_cleanup(void);

#ifdef __cplusplus
}
#endif

#endif /* GHOST_STACK_H */
