# xc2-recomp lifter (vendored, unmodified)

The ARM64-to-C lifter and code generator of XC2 Recomp (https://github.com/AksharDP/xc2-recomp), commit
`e9885513a2739fc68e3c5f341f192aa71f9926ce`, MIT licence (`LICENSE`). Only the modules the port imports are here:
`recomp/` (lifter, SIMD lowering, jump tables, flags, register planning, module and NSO loading, the generator
whose pieces `port/recomp/gen_il2cpp.py` reuses) and `tools/check_content.py` (the generated-file marker).

Do not edit these files; changes belong in `port/recomp/gen_il2cpp.py`, which subclasses the generator.
