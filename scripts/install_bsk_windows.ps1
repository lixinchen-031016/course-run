$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$version = "0.3.0"
$assetName = "bsk-v$version-x86_64-pc-windows-msvc.zip"
$expectedSha256 = "CD31665559D0FAAE2CFB79AB1C3CB6854BCE10B4FDE510BE015456E8370F629E"
$installDir = Join-Path $HOME ".local\bin"
$cacheDir = Join-Path $env:TEMP "bsk-install"
$zipPath = Join-Path $cacheDir $assetName

New-Item -ItemType Directory -Force -Path $installDir, $cacheDir | Out-Null
Remove-Item -Force -ErrorAction SilentlyContinue $zipPath

$urls = @(
    "https://github.com/Tencent/BrowserSkill/releases/download/cli-v$version/$assetName",
    "https://ghproxy.net/https://github.com/Tencent/BrowserSkill/releases/download/cli-v$version/$assetName",
    "https://gh-proxy.com/https://github.com/Tencent/BrowserSkill/releases/download/cli-v$version/$assetName"
)

$downloaded = $false
foreach ($url in $urls) {
    try {
        Write-Host "Downloading: $url"
        Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing -TimeoutSec 30
        $actualSha256 = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($actualSha256 -ne $expectedSha256) {
            throw "SHA256 mismatch. Expected $expectedSha256, got $actualSha256"
        }
        $downloaded = $true
        break
    }
    catch {
        Write-Warning "Download failed: $($_.Exception.Message)"
        Remove-Item -Force -ErrorAction SilentlyContinue $zipPath
    }
}

if (-not $downloaded) {
    throw "Unable to download BrowserSkill. Check your network, proxy, or download the official release manually."
}

Expand-Archive -Path $zipPath -DestinationPath $installDir -Force
$bskPath = Join-Path $installDir "bsk.exe"
if (-not (Test-Path $bskPath)) {
    throw "bsk.exe was not found after extraction: $bskPath"
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$installDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$installDir;$userPath", "User")
}
$env:Path = "$installDir;$env:Path"

Write-Host "BrowserSkill installed to: $installDir"
& $bskPath --version
