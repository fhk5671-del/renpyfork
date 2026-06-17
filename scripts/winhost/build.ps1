param(
    [string] $Output = ""
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$source = Join-Path $PSScriptRoot "host.cs"
$payloadInput = Join-Path $PSScriptRoot "host_payload.py"

if (-not $Output) {
    $Output = Join-Path $root "build\winhost\renpy_host.exe"
}

$outputDirectory = Split-Path -Parent $Output

if (-not (Test-Path $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}

if (-not (Test-Path $payloadInput)) {
    throw "Payload source not found: $payloadInput"
}

$payloadSource = Join-Path $outputDirectory "host_payload.g.cs"
$payloadKey = 0x37
$payloadBytes = [System.Text.Encoding]::UTF8.GetBytes([System.IO.File]::ReadAllText($payloadInput))

for ($i = 0; $i -lt $payloadBytes.Length; $i += 1) {
    $payloadBytes[$i] = $payloadBytes[$i] -bxor $payloadKey
}

$payloadText = [System.Convert]::ToBase64String($payloadBytes)
$builder = New-Object System.Text.StringBuilder
[void] $builder.AppendLine("internal static partial class Host")
[void] $builder.AppendLine("{")
[void] $builder.AppendLine("    private static readonly string[] PayloadData = new string[] {")

for ($i = 0; $i -lt $payloadText.Length; $i += 100) {
    $count = [Math]::Min(100, $payloadText.Length - $i)
    [void] $builder.AppendLine("        `"$($payloadText.Substring($i, $count))`",")
}

[void] $builder.AppendLine("    };")
[void] $builder.AppendLine("}")

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($payloadSource, $builder.ToString(), $utf8NoBom)

$compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (-not (Test-Path $compiler)) {
    $compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe"
}

if (-not (Test-Path $compiler)) {
    throw "Could not find csc.exe."
}

& $compiler /nologo /target:winexe /platform:x64 /optimize+ /out:$Output $source $payloadSource

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Output $Output
