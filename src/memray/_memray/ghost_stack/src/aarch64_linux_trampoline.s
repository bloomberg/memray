/**
 * GhostStack Return Trampoline - AArch64 Linux
 * =============================================
 *
 * This assembly implements the return address trampoline for shadow stack unwinding
 * on 64-bit ARM (AArch64) Linux systems.
 *
 * When GhostStack patches a return address to point here, this trampoline:
 *   1. Saves the function's return value registers (x0-x7)
 *   2. Calls ghost_trampoline_handler() to get the real return address
 *   3. Restores the return value registers and branches to the real address
 *
 * Exception Handling:
 *   The trampoline includes DWARF unwind info and an LSDA so C++ exceptions
 *   propagate correctly through patched frames. When an exception passes through,
 *   control goes to .L3 which calls ghost_exception_handler()
 *   to restore the real return address before rethrowing.
 *
 * AArch64 AAPCS64 ABI Notes:
 *   - Return values: x0-x7 (up to 8 registers for HFA/HVA or multi-value returns)
 *   - Link register: x30 (LR) holds return address
 *   - Frame pointer: x29 (FP)
 *   - Stack: 16-byte aligned, grows downward
 *
 * Pointer Authentication:
 *   If PAC is enabled, return addresses may be signed. The C++ code handles
 *   stripping the PAC before use (via xpaclri instruction).
 */

    .arch armv8-a
    .text
    .align    2
    .p2align 3,,7

    /* ==========================================================================
     * ghost_ret_trampoline_start - Exception handling anchor
     * ==========================================================================
     * This symbol marks the start of the function for DWARF unwinding.
     * CFI directives establish exception handling context:
     *   - .cfi_personality: Use __gxx_personality_v0 for C++ exceptions
     *   - .cfi_lsda: Point to our Language Specific Data Area
     *   - .cfi_undefined x30: Signal that LR (return address) is non-standard
     */
    .global    ghost_ret_trampoline_start
    .type    ghost_ret_trampoline_start, %function
ghost_ret_trampoline_start:
.LFB0:
    .cfi_startproc
    .cfi_personality 0x9b,DW.ref.__gxx_personality_v0
    .cfi_lsda 0x1b,.LLSDA0
    .cfi_undefined x30

    /* Exception try region - exceptions here redirect to .L3 */
.LEHB0:
    nop                         /* Placeholder marking exception region start */
.LEHE0:

    /* ==========================================================================
     * ghost_ret_trampoline - The actual trampoline entry point
     * ==========================================================================
     * When a function's return address has been patched to point here,
     * execution continues at this label upon function return (via RET).
     * The original return address is stored in GhostStack's shadow stack.
     */
.globl ghost_ret_trampoline
.type ghost_ret_trampoline, @function
ghost_ret_trampoline:

    /* -------------------------------------------------------------------------
     * Step 1: Save return value registers
     * -------------------------------------------------------------------------
     * AAPCS64 uses x0-x7 for return values (e.g., HFA types can use all 8).
     * We must preserve these across our callback.
     *
     * Stack layout after save (64 bytes = 8 registers * 8 bytes):
     *   sp+56: x7
     *   sp+48: x6
     *   sp+40: x5
     *   sp+32: x4
     *   sp+24: x3
     *   sp+16: x2
     *   sp+8:  x1
     *   sp+0:  x0
     *
     * Note: stp stores pairs of registers efficiently.
     */
    sub sp, sp, #(8 * 8)        /* Allocate 64 bytes (8 registers) */
    stp x0, x1, [sp, 0]         /* Save x0, x1 (primary return value pair) */
    stp x2, x3, [sp, 16]        /* Save x2, x3 */
    stp x4, x5, [sp, 32]        /* Save x4, x5 */
    stp x6, x7, [sp, 48]        /* Save x6, x7 */

    /* -------------------------------------------------------------------------
     * Step 2: Call into C++ to get the real return address
     * -------------------------------------------------------------------------
     * Argument (x0): Pointer to original stack location
     *   = sp (current) + 64 (saved regs) = original sp
     *
     * ghost_trampoline_handler() returns the real return address in x0.
     */
    mov x0, sp
    add x0, x0, #64             /* x0 = original stack pointer */
    bl ghost_trampoline_handler /* Call C++ handler; result in x0 */

    /* -------------------------------------------------------------------------
     * Step 3: Prepare return address and restore registers
     * -------------------------------------------------------------------------
     * Move real return address to x30 (LR) first, then restore x0-x7.
     * This order matters because x0 gets overwritten by ldp.
     */
    mov x30, x0                 /* x30 (LR) = real return address */

    /* Restore all return value registers */
    ldp x0, x1, [sp, 0]         /* Restore x0, x1 */
    ldp x2, x3, [sp, 16]        /* Restore x2, x3 */
    ldp x4, x5, [sp, 32]        /* Restore x4, x5 */
    ldp x6, x7, [sp, 48]        /* Restore x6, x7 */
    add sp, sp, #(8 * 8)        /* Deallocate stack frame */

    /* -------------------------------------------------------------------------
     * Step 4: Return to real caller
     * -------------------------------------------------------------------------
     * br x30 is an indirect branch to the address in x30.
     * Unlike 'ret', 'br' doesn't interact with return prediction,
     * which is appropriate since we're branching to an arbitrary address.
     */
    br x30                      /* Branch to real return address */
    nop                         /* Padding for alignment */

    /* ==========================================================================
     * Exception landing pad
     * ==========================================================================
     * When an exception propagates through our patched frame:
     *   1. Personality routine finds our LSDA entry
     *   2. Stack is unwound to our frame
     *   3. Control transfers here with exception object in x0
     *
     * We restore the real return address and rethrow so unwinding continues
     * correctly through the original call stack.
     */
.L3:
    /* x0 already contains exception object pointer from runtime */
    bl    ghost_exception_handler   /* Get real return addr */
    mov x30, x0                 /* Restore LR with real return address */
    b     __cxa_rethrow         /* Rethrow exception (tail call) */

    .cfi_endproc
.LFE0:

    /* ==========================================================================
     * LSDA (Language Specific Data Area)
     * ==========================================================================
     * This data tells __gxx_personality_v0 how to handle exceptions.
     *
     * Structure:
     *   - Header: encoding information
     *   - Call site table: maps PC ranges to landing pads
     *   - Action table: what to do at each landing pad
     *   - Type table: exception types to catch (0 = catch all)
     */
    .global    __gxx_personality_v0
    .section    .gcc_except_table,"a",@progbits
    .align    2
.LLSDA0:
    .byte    0xff                /* @LPStart encoding: omit (use function start) */
    .byte    0x9b                /* @TType encoding: indirect pcrel sdata4 */
    .uleb128 .LLSDATT0-.LLSDATTD0   /* @TType base offset */
.LLSDATTD0:
    .byte    0x1                 /* Call site encoding: uleb128 */
    .uleb128 .LLSDACSE0-.LLSDACSB0  /* Call site table length */
.LLSDACSB0:
    /* Call site entry for our try region */
    .uleb128 .LEHB0-.LFB0       /* Start of region (relative to function) */
    .uleb128 .LEHE0-.LEHB0      /* Length of region */
    .uleb128 .L3-.LFB0          /* Landing pad address (relative) */
    .uleb128 0x1                /* Action: index 1 in action table */
.LLSDACSE0:
    .byte    0x1                 /* Action table: filter type 1 */
    .byte    0                   /* No next action */
    .align    2
    .4byte    0                  /* Type table: 0 = catch(...) */

.LLSDATT0:
    .text
    .size    ghost_ret_trampoline_start, .-ghost_ret_trampoline_start

    /* ==========================================================================
     * Symbol references
     * ==========================================================================
     * Weak reference to __gxx_personality_v0 in a COMDAT group.
     * This allows multiple translation units to define it without conflicts.
     */
    .weak    DW.ref.__gxx_personality_v0
    .section    .data.rel.local.DW.ref.__gxx_personality_v0,"awG",@progbits,DW.ref.__gxx_personality_v0,comdat
    .align    3
    .type    DW.ref.__gxx_personality_v0, %object
    .size    DW.ref.__gxx_personality_v0, 8
DW.ref.__gxx_personality_v0:
    .xword    __gxx_personality_v0

    /* Mark stack as non-executable (security hardening) */
    .section    .note.GNU-stack,"",@progbits
