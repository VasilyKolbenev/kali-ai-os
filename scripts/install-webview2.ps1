# Install Microsoft WebView2 Runtime if not already present.
# Tauri shell (kali-desktop.exe) requires WebView2 to render the UI.
# Windows 11 has it pre-installed; older Win10 builds may need it.

$ErrorActionPreference = "SilentlyContinue"

function Test-WebView2Installed {
    $keys = @(
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BEB-E15CD01B5714}",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BEB-E15CD01B5714}",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BEB-E15CD01B5714}"
    )
    foreach ($key in $keys) {
        $version = (Get-ItemProperty -Path $key -Name "pv" -ErrorAction SilentlyContinue).pv
        if ($version) {
            Write-Host "WebView2 Runtime $version already installed (key: $key)"
            return $true
        }
    }
    return $false
}

if (Test-WebView2Installed) {
    exit 0
}

Write-Host "WebView2 Runtime not found. Downloading installer..."
$tempInstaller = Join-Path $env:TEMP "MicrosoftEdgeWebview2Setup.exe"
try {
    Invoke-WebRequest `
        -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" `
        -OutFile $tempInstaller `
        -UseBasicParsing
    Write-Host "Running WebView2 installer (silent)..."
    Start-Process -FilePath $tempInstaller -ArgumentList "/silent", "/install" -Wait
    Remove-Item $tempInstaller -Force -ErrorAction SilentlyContinue
    Write-Host "WebView2 Runtime install complete."
} catch {
    Write-Host "WebView2 install failed: $_"
    Write-Host "KALI may still launch — many systems have WebView2 from Edge."
    exit 0  # don't block install on this
}
