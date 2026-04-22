; KALI Premium 0.2.0-beta — Inno Setup script
; Supports >4GB installers (unlike 32-bit 7z SFX).
; Compile: iscc scripts\installer_premium.iss
; Output: dist_premium\KALI-Premium-Setup-0.2.0-beta.exe

#define AppName "KALI Premium"
#define AppVersion "0.2.0-beta"
#define AppPublisher "Vasily Kolbenev"
#define AppExe "kali-desktop.exe"

[Setup]
AppId={{B7A3F12E-KALI-PREMIUM-4F2C-2026042200}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/VasilyKolbenev/kali-ai-os
DefaultDirName={autopf}\KALI
DefaultGroupName=KALI
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
OutputDir=..\dist_premium
OutputBaseFilename=KALI-Premium-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4

; x64 only — we ship CUDA torch which needs 64-bit
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; User-scope install (no UAC prompt for most users)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Modern UI
WizardStyle=modern
DisableWelcomePage=no
DisableDirPage=no
DisableReadyPage=no
AllowCancelDuringInstall=yes
ShowLanguageDialog=no
SetupIconFile=..\src-tauri\icons\icon.ico
WizardImageFile=compiler:WizModernImage-IS.bmp
WizardSmallImageFile=compiler:WizModernSmallImage-IS.bmp

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные значки:"
Name: "startmenuicon"; Description: "Добавить в меню Пуск"; GroupDescription: "Дополнительные значки:"

[Files]
; Source is the pre-staged premium bundle
; Exclude SFX-specific artifacts (install.bat + sfx_config.txt) — InnoSetup replaces them
Source: "..\dist_premium\premium_stage\*"; DestDir: "{app}"; \
    Excludes: "install.bat,sfx_config.txt"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\KALI"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: startmenuicon
Name: "{group}\Удалить KALI"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{autodesktop}\KALI"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; Install WebView2 runtime if missing (Tauri shell needs it)
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -Command ""if (-not (Test-Path 'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BEB-E15CD01B5714}')) {{ Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $env:TEMP\WebView2Setup.exe; Start-Process -Wait $env:TEMP\WebView2Setup.exe -ArgumentList '/silent /install'; Remove-Item $env:TEMP\WebView2Setup.exe }}"""; \
    StatusMsg: "Проверяем WebView2 Runtime..."; \
    Flags: runhidden waituntilterminated

; Launch KALI after install
Filename: "{app}\{#AppExe}"; Description: "Запустить KALI"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Optional: clean app data on uninstall (commented out by default — preserve user agents/config)
; Type: filesandordirs; Name: "{userappdata}\KALI"

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // Ensure no running KALI instance blocks file overwrite
  Exec('taskkill.exe', '/IM kali-backend.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/IM kali-desktop.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;
