# xc2_xlate.exe: Switch shader translator

Translates the Switch GPU's shader programs (as stored in the game's Unity shader assets) to SPIR-V.
`port\shaders\xlate.py` runs it (`xc2_xlate.exe <jobs.json> <out dir>`); `port\shaders\spv_fix.py` then adapts the
result to Unity's Vulkan conventions.

The binary is taken unmodified from the Windows release 0.1.12 of XC2 Recomp
(https://github.com/AksharDP/xc2-recomp/releases/tag/v0.1.12, `XC2-Setup/bin/xc2_xlate.exe`,
SHA-256 `465397a2296e15e30e0425405edec013a2880c11e4eeef5025cfd48cb07c2631`). `xc2_xlate.id` is that build's
identity string.

It is a NativeAOT build of the Ryujinx shader translator 1.3.2 with MacNativeGames' optimizer patches and
translator tool and XC2 Recomp's own patches. To build it from source, use `tools/build_xlate.py` of XC2 Recomp
(needs the .NET SDK and the MSVC build tools), and point the port at the result with the `XLATE` environment
variable.

Licences: all MIT. `LICENSE.xc2-recomp.txt`, `LICENSE.Ryujinx.txt`, `MacNativeGames-LICENSE.txt` in this folder.
