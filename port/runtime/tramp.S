# Guest -> host Win64 call trampoline.
#   uint64_t rt_win64_call(void *fn, const uint64_t *slots, uint64_t nslots, uint64_t *xmm0_out)
# Each 64-bit slot i < 4 is loaded into both the integer register and the SSE register of its position, so integer,
# float and double arguments all work without a mask; slots >= 4 go to the stack. Returns rax; xmm0 is stored to
# *xmm0_out. Has SEH unwind info so that a host unwind (thunk.cpp) can cross it.
    .text
    .globl rt_win64_call
    .def rt_win64_call; .scl 2; .type 32; .endef
    .seh_proc rt_win64_call
rt_win64_call:
    pushq %rbp
    .seh_pushreg %rbp
    pushq %rsi
    .seh_pushreg %rsi
    pushq %rdi
    .seh_pushreg %rdi
    pushq %rbx
    .seh_pushreg %rbx
    subq $8, %rsp
    .seh_stackalloc 8
    leaq (%rsp), %rbp
    .seh_setframe %rbp, 0
    .seh_endprologue
    movq %r9, %rbx              # xmm0_out
    movq %rdx, %rsi             # slots
    movq %rcx, %rax             # fn
    movq %r8, %rcx              # n
    cmpq $4, %rcx
    jae 1f
    movq $4, %rcx
1:  incq %rcx
    andq $-2, %rcx              # even number of slots keeps rsp 16-aligned
    leaq (,%rcx,8), %rdx
    subq %rdx, %rsp
    movq %rsp, %rdi
    movq %r8, %rcx
    cmpq $4, %rcx
    jae 2f
    movq $4, %rcx
2:  cld
    rep movsq                   # copy all slots (the first four land in the home area)
    movq 0(%rsp), %rcx
    movq 8(%rsp), %rdx
    movq 16(%rsp), %r8
    movq 24(%rsp), %r9
    movq %rcx, %xmm0
    movq %rdx, %xmm1
    movq %r8, %xmm2
    movq %r9, %xmm3
    callq *%rax
    testq %rbx, %rbx
    jz 3f
    movq %xmm0, (%rbx)
3:  leaq 8(%rbp), %rsp
    popq %rbx
    popq %rdi
    popq %rsi
    popq %rbp
    retq
    .seh_endproc

# Host-callable entry stubs for guest functions (callback.c) jump here with r10 = the stub's descriptor.
#   uint64_t rt_callback_entry(Descriptor *d /*r10*/, rcx, rdx, r8, r9, stack...)
# Spills the four register arguments to their home slots and calls rt_callback_dispatch(d, args) where args points at
# the home area (args[0..3] = register arguments, args[4..] = stack arguments).
    .globl rt_callback_entry
    .def rt_callback_entry; .scl 2; .type 32; .endef
    .seh_proc rt_callback_entry
rt_callback_entry:
    movq %rcx, 8(%rsp)
    movq %rdx, 16(%rsp)
    movq %r8, 24(%rsp)
    movq %r9, 32(%rsp)
    subq $88, %rsp
    .seh_stackalloc 88
    .seh_endprologue
    movq %xmm0, 32(%rsp)
    movq %xmm1, 40(%rsp)
    movq %xmm2, 48(%rsp)
    movq %xmm3, 56(%rsp)
    movq %r10, %rcx
    leaq 96(%rsp), %rdx         # integer view of the arguments
    leaq 32(%rsp), %r8          # SSE view of the first four
    leaq 64(%rsp), %r9          # out: xmm0 result
    callq rt_callback_dispatch
    movq 64(%rsp), %xmm0
    addq $88, %rsp
    retq
    .seh_endproc
