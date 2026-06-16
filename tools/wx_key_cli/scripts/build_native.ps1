param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    [ValidateSet("x64")]
    [string]$Platform = "x64",
    [switch]$SkipAssetCopy
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$projectPath = Join-Path $repoRoot "wx_key\wx_key.vcxproj"
$assetDllPath = Join-Path $repoRoot "dist\wx_key.dll"
$builtDllPath = Join-Path $repoRoot "wx_key\$Platform\$Configuration\wx_key.dll"

function Get-VCTargetsPathForMSBuild {
    param([string]$MSBuildPath)

    if (-not (Test-Path $MSBuildPath)) {
        return $null
    }

    $msbuildDir = Split-Path -Parent $MSBuildPath
    $candidateRoots = @(
        (Join-Path $msbuildDir "..\..\Microsoft\VC\v170"),
        (Join-Path $msbuildDir "..\..\..\Microsoft\VC\v170")
    )

    foreach ($root in $candidateRoots) {
        $resolved = Resolve-Path $root -ErrorAction SilentlyContinue
        if (-not $resolved) {
            continue
        }
        $propsPath = Join-Path $resolved.Path "Microsoft.Cpp.Default.props"
        if (Test-Path $propsPath) {
            return ($resolved.Path.TrimEnd("\") + "\")
        }
    }

    return $null
}

function Get-VSInstallRootForMSBuild {
    param([string]$MSBuildPath)

    $resolved = Resolve-Path $MSBuildPath -ErrorAction SilentlyContinue
    if (-not $resolved) {
        return $null
    }

    $path = $resolved.Path
    $marker = "\MSBuild\Current\Bin"
    $index = $path.IndexOf($marker, [System.StringComparison]::OrdinalIgnoreCase)
    if ($index -lt 0) {
        return $null
    }

    return $path.Substring(0, $index)
}

function Test-VSHasCppCompiler {
    param([string]$InstallRoot)

    if (-not $InstallRoot) {
        return $false
    }

    $vcToolsRoot = Join-Path $InstallRoot "VC\Tools\MSVC"
    if (-not (Test-Path $vcToolsRoot)) {
        return $false
    }

    $cl = Get-ChildItem -Path $vcToolsRoot -Recurse -Filter cl.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "\\bin\\Host(x64|x86)\\x64\\cl\.exe$" } |
        Select-Object -First 1

    return [bool]$cl
}

$msbuildCandidates = @()
if ($env:MSBUILD_PATH) {
    $msbuildCandidates += $env:MSBUILD_PATH
}

$pathMsbuild = Get-Command msbuild.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
if ($pathMsbuild) {
    $msbuildCandidates += $pathMsbuild
}

$vswhereCandidates = @(
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\Installer\vswhere.exe"
)
$vswhere = $vswhereCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($vswhere) {
    $vsInstallPath = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($vsInstallPath) {
        $msbuildCandidates += (Join-Path $vsInstallPath "MSBuild\Current\Bin\MSBuild.exe")
        $msbuildCandidates += (Join-Path $vsInstallPath "MSBuild\Current\Bin\amd64\MSBuild.exe")
    }
}

$msbuildCandidates = @(
    $msbuildCandidates
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Enterprise\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
) | Where-Object { $_ }

$msbuild = $null
$vcTargetsPath = $null
$vsInstallRoot = $null
$vsDevCmd = $null
foreach ($candidate in $msbuildCandidates) {
    $candidateVCTargetsPath = Get-VCTargetsPathForMSBuild $candidate
    $candidateInstallRoot = Get-VSInstallRootForMSBuild $candidate
    if ($candidateVCTargetsPath -and (Test-VSHasCppCompiler $candidateInstallRoot)) {
        $msbuild = $candidate
        $vcTargetsPath = $candidateVCTargetsPath
        $vsInstallRoot = $candidateInstallRoot
        $vsDevCmd = Join-Path $vsInstallRoot "Common7\Tools\VsDevCmd.bat"
        break
    }
}

if (-not $msbuild) {
    throw "MSBuild with the MSVC x64 compiler was not found. Install Visual Studio 2022 or Build Tools 2022 with Desktop development with C++, including MSVC v143 and a Windows SDK, or set MSBUILD_PATH to that installation's MSBuild.exe."
}

# Some shells expose both PATH and Path. MSBuild can fail when both exist.
$pathValue = $env:Path
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")

if (Test-Path $vsDevCmd) {
    $cmd = "`"$vsDevCmd`" -arch=x64 -host_arch=x64 >nul && `"$msbuild`" `"$projectPath`" /p:Configuration=$Configuration /p:Platform=$Platform /m"
    cmd.exe /s /c $cmd
} else {
    & $msbuild $projectPath /p:Configuration=$Configuration /p:Platform=$Platform /m
}
if ($LASTEXITCODE -ne 0) {
    throw "Native build failed."
}

if (-not $SkipAssetCopy) {
    New-Item -ItemType Directory -Force -Path (Split-Path $assetDllPath) | Out-Null
    Copy-Item -LiteralPath $builtDllPath -Destination $assetDllPath -Force
    Write-Host "Copied native DLL to $assetDllPath"
}
