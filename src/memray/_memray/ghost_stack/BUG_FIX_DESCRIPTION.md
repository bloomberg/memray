# Ghost Stack Bug Fix

## Problem

The ghost unwind feature was producing incorrect native stack traces. When `fast_unwind=True`, the captured stack was missing the top frames (like `valloc`) and showed frames shifted by one position.

## Root Causes

### Bug 1: Returning Return Addresses Instead of Instruction Pointers

The `unw_backtrace()` function returns **instruction pointers (IPs)** - the address where each frame is currently executing. However, ghost_stack was returning **return addresses** - the address where each frame will return TO after it completes.

These are different values:
- IP of frame N = where frame N is executing
- Return address stored in frame N = IP of frame N-1 (the caller)

So returning return addresses produces a stack that is shifted by one frame and missing the topmost frame entirely.

**Location**: `capture_and_install()` and `copy_cached_frames()` in `ghost_stack.cpp`

**Fix**:
1. Added `ip` field to `StackEntry` struct to store both the IP (for returning to caller) and the return_address (for trampoline restoration)
2. Changed output buffer to return `entries_[i].ip` instead of `entries_[i].return_address`

### Bug 2: Off-by-One Error in Frame Walking Loop

The original loop structure was:
```cpp
while (unw_step(&cursor) > 0 && frame_idx < raw_count) {
    unw_get_reg(&cursor, UNW_REG_IP, &ip);  // Read AFTER stepping
    ...
}
```

This calls `unw_step()` BEFORE reading frame data. After the skip loop positions the cursor at frame 3, the first `unw_step()` moves to frame 4 before we read anything - skipping frame 3 entirely.

**Fix**: Changed to read-then-step pattern:
```cpp
do {
    unw_get_reg(&cursor, UNW_REG_IP, &ip);  // Read FIRST
    ...
    step_result = unw_step(&cursor);         // Step AFTER
} while (step_result > 0);
```

## Files Modified

- `src/memray/_memray/ghost_stack/src/ghost_stack.cpp`
  - `StackEntry` struct: added `ip` field
  - `capture_and_install()`: store IP, return IP, fix loop structure
  - `copy_cached_frames()`: return IP instead of return_address

## Test

The fix was verified with:
```
python -m pytest tests/integration/test_native_tracking.py -v -s -x -k ceval
```

Both `fast_unwind=False` and `fast_unwind=True` variants now pass and produce correct stack traces with `valloc` and `run_recursive` in the expected positions.
