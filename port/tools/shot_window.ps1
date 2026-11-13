# Capture the game window's own content (not the screen, so other windows never appear) at the given times.
# Where the execution policy blocks script files, run it as:
#   & ([scriptblock]::Create((Get-Content -Raw port\tools\shot_window.ps1))) -Out C:\dir\prefix -At 30,60
param([string]$Out, [int[]]$At, [int]$MaxWidth = 1600, [string]$Process = '*Slop')
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class BRShot { [StructLayout(LayoutKind.Sequential)] public struct R { public int l,t,r,b; }
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }
'@
[BRShot]::SetProcessDPIAware() | Out-Null
$t0 = Get-Date
foreach ($s in $At) {
    $w = $s - ((Get-Date) - $t0).TotalSeconds
    if ($w -gt 0) { Start-Sleep -Milliseconds ([int]($w * 1000)) }
    $p = Get-Process $Process -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if (-not $p) { "shot ${s}: no window"; continue }
    $r = New-Object BRShot+R
    [BRShot]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
    $bw = $r.r - $r.l; $bh = $r.b - $r.t
    if ($bw -le 0) { continue }
    $bmp = New-Object System.Drawing.Bitmap $bw, $bh
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $dc = $g.GetHdc(); $ok = [BRShot]::PrintWindow($p.MainWindowHandle, $dc, 2); $g.ReleaseHdc($dc)
    if ($bw -gt $MaxWidth) {
        $small = New-Object System.Drawing.Bitmap $bmp, $MaxWidth, ([int]($bh * $MaxWidth / $bw))
        $small.Save("${Out}_$s.png"); $small.Dispose()
    } else { $bmp.Save("${Out}_$s.png") }
    $g.Dispose(); $bmp.Dispose()
    "shot ${s}: ${bw}x${bh} ok=$ok"
}
