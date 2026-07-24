; KALI Premium 1.0.0-rc3 — Inno Setup script
; Supports >4GB installers (unlike 32-bit 7z SFX).
; Compile: iscc scripts\installer_premium.iss
; Output: dist_premium\KALI-Premium-Setup-1.0.0-rc3.exe

#define AppName "KALI Premium"
#define AppVersion "1.0.0-rc3"
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

; Code signing (C7/OPUS-201): a SIGNED build passes /DSignSetup plus a named
; SignTool command (/Skali="...") to ISCC. Both the Setup AND the generated
; uninstaller are then Authenticode-signed. An INTERNAL build omits the define
; and compiles unsigned (the .bat renames the output to the explicit
; INTERNAL-UNSIGNED-DO-NOT-DISTRIBUTE artifact). .bin slices are NOT signed
; separately — the signed Setup protects them via Inno's own checksums.
#ifdef SignSetup
SignTool=kali
SignedUninstaller=yes
#endif

; DiskSpanning is MANDATORY: Inno hard-errors on any installation over
; ~4.2 GB in a single Setup.exe (Windows loader limit — first compile of the
; single-file variant failed exactly there, 2026-07-13; the premium bundle is
; ~5.8 GB uncompressed). Ships Setup.exe + .bin slices; distribute as ONE zip
; so a non-tech user cannot lose a slice (CDN A3 covers resumable download).
DiskSpanning=yes
DiskSliceSize=2000000000

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
; [Files] reads ONLY from premium_stage (C7/OPUS-103): the transactional stage
; composer stages install-webview2.ps1 into premium_stage, so it arrives via the
; glob below — no external Source pulls anything in past the sealed stage.
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

; Auto-update: тихая установка перезапускает апп сама (обычная установка
; использует postinstall-строку выше; skipifnotsilent исключает двойной запуск).
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Flags: nowait skipifnotsilent

[UninstallDelete]
; Optional: clean app data on uninstall (commented out by default — preserve user agents/config)
; Type: filesandordirs; Name: "{userappdata}\KALI"

[Code]
function ProcessRunning(const ExeName: string): Boolean;
var
  ResultCode: Integer;
begin
  // tasklist + find: find выходит с 0, если имя найдено (процесс жив)
  Exec('cmd.exe', '/c tasklist /FI "IMAGENAME eq ' + ExeName + '" | find /I "' + ExeName + '" > nul',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
  Waited: Integer;
begin
  Exec('taskkill.exe', '/IM kali-backend.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/IM kali-desktop.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // Ждём реального исчезновения процессов (до ~10 с) — иначе file-in-use при копировании.
  Waited := 0;
  while (Waited < 10000) and (ProcessRunning('kali-backend.exe') or ProcessRunning('kali-desktop.exe')) do
  begin
    Sleep(500);
    Waited := Waited + 500;
  end;
  // Если процесс жив после таймаута — продолжаем; /SUPPRESSMSGBOXES авто-абортит
  // на file-in-use (принятый v1 fail-режим, спека «Инсталятор §2»).
  Result := True;
end;
