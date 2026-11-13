# Capture the primary screen to PNG files at the given times (seconds from now):
#   powershell -File shot.ps1 -Out C:\dir\prefix -At 30,60,90
# Used to look at a windowed player run from a script (the file name gets _<seconds>.png appended).
param([string]$Out, [int[]]$At)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$t0 = Get-Date
foreach ($s in $At) {
    $wait = $s - ((Get-Date) - $t0).TotalSeconds
    if ($wait -gt 0) { Start-Sleep -Milliseconds ([int]($wait * 1000)) }
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $small = New-Object System.Drawing.Bitmap $bmp, ([int]($b.Width / 2)), ([int]($b.Height / 2))
    $small.Save("${Out}_$s.png", [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose(); $small.Dispose()
}
