; KALI Premium 0.2.0-beta — Inno Setup script
; Supports >4GB installers (unlike 32-bit 7z SFX).
; Compile: iscc scripts\installer_premium.iss
; Output: dist_premium\KALI-Premium-Setup-0.2.0-beta.exe

#define AppName "KALI Premium"
#define AppVersion "0.2.0-beta"
#define AppPublisher "Vasily Kolbenev"
#define AppExe "kali-desktop.exe"

[Setup]
; AppId is the stable GUID identifying this app for upgrade/uninstall detection.
; Must be a valid GUID and must NOT change after a public release — a new value
; installs side-by-side instead of upgrading the prior install.
AppId={{B7A3F12E-4F2C-4A2B-9E5D-202604220000}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/VasilyKolbenev/kali-ai-os
DefaultDirName={autopf}\KALI
DefaultGroupName=KALI
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
OutputDir=..\dist_premium\installer
OutputBaseFilename=KALI-Premium-Setup-{#AppVersion}
Compression=lzma2/ultra64
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4

; Single-file output. The legacy DiskSpanning split (.exe + .bin slices) was a
; workaround for the retired 32-bit 7z SFX 4 GB limit; Inno Setup's 64-bit
; compiler has no such limit, so we ship one self-contained .exe (no .bin
; slices for a non-tech user to lose).
DiskSpanning=no

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
; Install WebView2 runtime if missing (Tauri shell needs it).
; Wrapped in a bootstrapper .ps1 file to avoid Inno's {...} constant parsing.
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install-webview2.ps1"""; \
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
