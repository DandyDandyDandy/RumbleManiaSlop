# The glyph atlas (icons/glyphs.png, see port/tools/make_glyphs.py) as data of the DLL, for pc_glyphs.c.
    .section .rdata,"dr"
    .globl rt_glyphs_png
    .globl rt_glyphs_png_end
rt_glyphs_png:
    .incbin "icons/glyphs.png"
rt_glyphs_png_end:
    .byte 0
