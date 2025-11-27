/**
 * GhostStack Return Trampoline - x86_64 Linux
 * ============================================
 *
 * This assembly implements the return address trampoline for shadow stack unwinding.
 * When GhostStack patches a return address to point here, this trampoline:
 *   1. Saves the function's return value (preserved across the callback)
 *   2. Calls ghost_trampoline_handler() to get the real return address
 *   3. Restores the return value and jumps to the real return address
 *
 * Exception Handling:
 *   The trampoline includes DWARF unwind info and an LSDA (Language Specific Data Area)
 *   so that C++ exceptions can propagate correctly through patched frames. When an
 *   exception passes through, the personality routine directs control to .L3, which
 *   calls ghost_exception_handler() to restore the real return address
 *   before rethrowing.
 *
 * Key insight: The .cfi_undefined rip directive tells the unwinder that the return
 * address is not in a standard location - this is intentional since we've patched it.
 *
 * x86_64 SysV ABI Notes:
 *   - Return values: rax (integer/pointer), rdx (second value), xmm0/xmm1 (floating point)
 *   - We save rax, rdx, and rcx (used by some ABIs like Rust for extra return values)
 *   - Stack must be 16-byte aligned before CALL instruction
 */

    .text
    .section    .text.unlikely,"ax",@progbits
.LCOLDB0:
    .text
.LHOTB0:
    .p2align 4

    /* ==========================================================================
     * ghost_ret_trampoline_start - Exception handling anchor
     * ==========================================================================
     * This symbol marks the start of the function for DWARF unwinding purposes.
     * The CFI directives set up exception handling:
     *   - .cfi_personality: Use __gxx_personality_v0 for C++ exceptions
     *   - .cfi_lsda: Point to our Language Specific Data Area for catch clauses
     *   - .cfi_undefined rip: Signal that return address is non-standard
     */
    .globl    ghost_ret_trampoline_start
    .hidden    ghost_ret_trampoline_start
    .type    ghost_ret_trampoline_start, @function
ghost_ret_trampoline_start:
.LFB0:
    .cfi_startproc
    .cfi_personality 0x9b,DW.ref.__gxx_personality_v0
    .cfi_lsda 0x1b,.LLSDA0
    .cfi_undefined rip

    /* Exception try region starts here - any exception in this region
     * will be caught and redirected to .L3 for proper handling */
.LEHB0:
    nop                         /* Placeholder for exception region start */
.LEHE0:

    /* ==========================================================================
     * ghost_ret_trampoline - The actual trampoline entry point
     * ==========================================================================
     * When a function returns and its return address has been patched to point
     * here, execution continues at this label. The original return address is
     * stored in GhostStack's shadow stack and will be retrieved via callback.
     */
.globl ghost_ret_trampoline
.type ghost_ret_trampoline, @function
ghost_ret_trampoline:
.intel_syntax noprefix

    /* -------------------------------------------------------------------------
     * Step 1: Save return values
     * -------------------------------------------------------------------------
     * The function we're returning from may have placed values in these registers.
     * We must preserve them across our callback to ghost_trampoline_handler().
     *
     * Stack layout after saves:
     *   rsp+24: original rsp (return address location)
     *   rsp+16: saved rax (primary return value)
     *   rsp+8:  saved rdx (secondary return value, e.g., for 128-bit returns)
     *   rsp:    saved rcx (used by Rust ABI, also scratch in some cases)
     *   [then -8 for alignment]
     */
    push rax                    /* Save primary return value */
    push rdx                    /* Save secondary return value */
    push rcx                    /* Save rcx (Rust ABI uses this) */

    /* Align stack to 16-byte boundary (required by SysV ABI before CALL).
     * We've pushed 3 * 8 = 24 bytes. Adding 8 makes it 32, which is aligned. */
    sub rsp, 8

    /* -------------------------------------------------------------------------
     * Step 2: Call into C++ to get the real return address
     * -------------------------------------------------------------------------
     * Argument (rdi): Pointer to where the return address *would* be on stack
     *   = rsp + 8 (alignment) + 8 (rcx) + 8 (rdx) + 8 (rax) = rsp + 32
     * This lets the C++ code verify stack pointer consistency if desired.
     *
     * ghost_trampoline_handler() returns the real return address in rax.
     */
    mov rdi, rsp
    add rdi, 32                 /* rdi = &original_return_addr_location */
    call ghost_trampoline_handler

    /* -------------------------------------------------------------------------
     * Step 3: Restore and jump to real return address
     * -------------------------------------------------------------------------
     * rax now contains the real return address. Move it to rsi (callee-saved
     * across our restores), restore the original return values, then jump.
     */
    mov rsi, rax                /* Save real return address */
    add rsp, 8                  /* Remove alignment padding */
    pop rcx                     /* Restore rcx */
    pop rdx                     /* Restore secondary return value */
    pop rax                     /* Restore primary return value */
    jmp rsi                     /* Jump to real return address */

.att_syntax

    /* ==========================================================================
     * Exception landing pad (hot path handoff)
     * ==========================================================================
     * If an exception is thrown while executing in the try region (.LEHB0-.LEHE0),
     * the C++ runtime's personality function sees our LSDA entry and directs
     * unwinding here. We save the exception object and jump to the cold handler.
     */
.L3:
    movq    %rax, %rdi          /* Exception object pointer -> first argument */
    jmp    .L2                  /* Jump to cold exception handler */

    .globl    __gxx_personality_v0

    /* ==========================================================================
     * LSDA (Language Specific Data Area)
     * ==========================================================================
     * This data tells __gxx_personality_v0 how to handle exceptions in our code.
     * Format: DWARF exception handling tables
     *
     * Key fields:
     *   - Call site table: Maps PC ranges to landing pads
     *   - Action table: What to do when landing (0 = cleanup, >0 = catch)
     *   - Type table: Exception types to catch (not used here, we catch all)
     */
    .section    .gcc_except_table,"a",@progbits
    .align 4
.LLSDA0:
    .byte    0xff                /* @LPStart encoding: omit (use function start) */
    .byte    0x9b                /* @TType encoding: indirect pcrel sdata4 */
    .uleb128 .LLSDATT0-.LLSDATTD0   /* @TType base offset */
.LLSDATTD0:
    .byte    0x1                 /* Call site encoding: uleb128 */
    .uleb128 .LLSDACSE0-.LLSDACSB0  /* Call site table length */
.LLSDACSB0:
    /* Call site entry: try region that catches exceptions */
    .uleb128 .LEHB0-.LFB0       /* Region start (relative to function) */
    .uleb128 .LEHE0-.LEHB0      /* Region length */
    .uleb128 .L3-.LFB0          /* Landing pad (where to go on exception) */
    .uleb128 0x1                /* Action: index into action table (catch-all) */
.LLSDACSE0:
    .byte    0x1                 /* Action table entry: catch type index 1 */
    .byte    0                   /* No next action */
    .align 4
    .long    0                   /* Type table entry: 0 = catch(...) */

.LLSDATT0:
    .text
    .cfi_endproc

    /* ==========================================================================
     * Cold exception handler
     * ==========================================================================
     * This is the "cold" (unlikely) path for exception handling. Placed in a
     * separate section to improve instruction cache locality of the hot path.
     *
     * When we get here:
     *   1. An exception was thrown
     *   2. The personality function found our LSDA
     *   3. Stack was unwound to our frame
     *   4. Control transferred to .L3, then here
     *
     * We must:
     *   1. Get the real return address from GhostStack
     *   2. Push it so __cxa_rethrow can continue unwinding correctly
     *   3. Rethrow the exception
     */
    .section    .text.unlikely
    .cfi_startproc
    .cfi_personality 0x9b,DW.ref.__gxx_personality_v0
    .cfi_lsda 0x1b,.LLSDAC0
    .type    ghost_ret_trampoline_start.cold, @function
ghost_ret_trampoline_start.cold:
.LFSB0:
.L2:
    /* rdi already contains exception pointer from .L3 */
    call    ghost_exception_handler

    /* rax = real return address. Push it onto stack so the unwinder
     * sees correct return address when __cxa_rethrow continues. */
    push %rax

    /* Rethrow the exception - unwinding continues from real return address */
    jmp     __cxa_rethrow@PLT
    .cfi_endproc
.LFE0:

    /* LSDA for cold section (empty - no more catching needed) */
    .section    .gcc_except_table
    .align 4
.LLSDAC0:
    .byte    0xff
    .byte    0x9b
    .uleb128 .LLSDATTC0-.LLSDATTDC0
.LLSDATTDC0:
    .byte    0x1
    .uleb128 .LLSDACSEC0-.LLSDACSBC0
.LLSDACSBC0:
.LLSDACSEC0:
    .byte    0x1
    .byte    0
    .align 4
    .long    0

.LLSDATTC0:
    .section    .text.unlikely
    .text
    .size    ghost_ret_trampoline_start, .-ghost_ret_trampoline_start
    .section    .text.unlikely
    .size    ghost_ret_trampoline_start.cold, .-ghost_ret_trampoline_start.cold
.LCOLDE0:
    .text
.LHOTE0:

    /* ==========================================================================
     * Symbol definitions
     * ==========================================================================
     * Reference to __gxx_personality_v0 for exception handling.
     * Placed in a COMDAT group so multiple TUs can define it.
     */
    .hidden    DW.ref.__gxx_personality_v0
    .weak    DW.ref.__gxx_personality_v0
    .section    .data.rel.local.DW.ref.__gxx_personality_v0,"awG",@progbits,DW.ref.__gxx_personality_v0,comdat
    .align 8
    .type    DW.ref.__gxx_personality_v0, @object
    .size    DW.ref.__gxx_personality_v0, 8
DW.ref.__gxx_personality_v0:
    .quad    __gxx_personality_v0

    /* Hide internal symbols from dynamic linking */
    .hidden    ghost_exception_handler
    .hidden    ghost_trampoline_handler

    /* Mark stack as non-executable (security) */
    .section    .note.GNU-stack,"",@progbits
