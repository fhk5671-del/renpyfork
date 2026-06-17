param(
    [string] $SdkRoot = "C:\Users\super\Dropbox\renpy-8.4.1-rnx-sdk",
    [string] $LauncherExe = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

if (-not $LauncherExe) {
    $LauncherExe = Join-Path $repoRoot "build\winhost\renpy_host.exe"
}

$sdkRootPath = [System.IO.Path]::GetFullPath($SdkRoot)
$launcherExePath = [System.IO.Path]::GetFullPath($LauncherExe)
$targetExe = [System.IO.Path]::GetFullPath((Join-Path $sdkRootPath "lib\py3-windows-x86_64\renpy_host.exe"))
$distributePath = [System.IO.Path]::GetFullPath((Join-Path $sdkRootPath "launcher\game\distribute.rpy"))
$buildPath = [System.IO.Path]::GetFullPath((Join-Path $sdkRootPath "renpy\common\00build.rpy"))
$staleCheatPaths = @(
    [System.IO.Path]::GetFullPath((Join-Path $sdkRootPath "renpy\common\00cheatmenu.rpy")),
    [System.IO.Path]::GetFullPath((Join-Path $sdkRootPath "renpy\common\00cheatmenu.rpyc"))
)

foreach ($path in @($targetExe, $distributePath, $buildPath) + $staleCheatPaths) {
    if (-not $path.StartsWith($sdkRootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside SDK root: $path"
    }
}

if (-not (Test-Path $launcherExePath)) {
    throw "Launcher template not found: $launcherExePath"
}

if (-not (Test-Path (Split-Path -Parent $targetExe))) {
    throw "SDK Windows runtime directory not found: $(Split-Path -Parent $targetExe)"
}

function Backup-Once($Path) {
    $backup = $Path + ".bak-before-winhost"

    if (-not (Test-Path $backup)) {
        Copy-Item -LiteralPath $Path -Destination $backup
    }
}

Copy-Item -LiteralPath $launcherExePath -Destination $targetExe -Force

foreach ($path in $staleCheatPaths) {
    Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
}

Backup-Once $distributePath
Backup-Once $buildPath

$buildText = [System.IO.File]::ReadAllText($buildPath)

if ($buildText -notmatch [regex]::Escape('lib/*/renpy_host.exe')) {
    $needle = '        ( "lib/*/renpy.exe", None),'
    $replacement = $needle + "`r`n" + '        ( "lib/*/renpy_host.exe", None),'

    if (-not $buildText.Contains($needle)) {
        throw "Could not find renpy.exe ignore line in $buildPath"
    }

    $buildText = $buildText.Replace($needle, $replacement)
    [System.IO.File]::WriteAllText($buildPath, $buildText)
}

$distText = [System.IO.File]::ReadAllText($distributePath)

if ($distText -notmatch [regex]::Escape('renpy_host.exe')) {
    $needle = '                src = os.path.join(config.renpy_base, src)'
    $replacement = '                if not os.path.isabs(src):' + "`r`n" + '                    src = os.path.join(config.renpy_base, src)' + "`r`n"

    if (-not $distText.Contains($needle)) {
        throw "Could not find exe source normalization line in $distributePath"
    }

    $distText = $distText.Replace($needle, $replacement)

    $needle = '            write_exe("lib/py3-windows-x86_64/renpy.exe", self.exe, self.exe, windows)'
    $replacement = @(
        '            renpy_exe = os.path.join(config.renpy_base, "lib", "py3-windows-x86_64", "renpy_host.exe")',
        '',
        '            if not os.path.exists(renpy_exe):',
        '                renpy_exe = "lib/py3-windows-x86_64/renpy.exe"',
        '',
        '            write_exe(renpy_exe, self.exe, self.exe, windows)'
    ) -join "`r`n"

    if (-not $distText.Contains($needle)) {
        throw "Could not find Windows renpy.exe writer line in $distributePath"
    }

    $distText = $distText.Replace($needle, $replacement)
    [System.IO.File]::WriteAllText($distributePath, $distText)
}

Write-Output "Installed $targetExe"
