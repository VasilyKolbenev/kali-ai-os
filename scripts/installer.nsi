; KALI Installer Script (NSIS)
; Builds: KALI-Setup-0.1.0.exe
;
; Prerequisites: NSIS installed (winget install NSIS.NSIS)
; Build: makensis scripts/installer.nsi

!include "MUI2.nsh"

; --- General ---
Name "KALI"
OutFile "..\dist\KALI-Setup-0.1.0.exe"
InstallDir "$PROGRAMFILES64\KALI"
RequestExecutionLevel admin

; --- UI ---
!define MUI_ICON "..\src-tauri\icons\icon.ico"
!define MUI_UNICON "..\src-tauri\icons\icon.ico"
!define MUI_WELCOMEPAGE_TITLE "Welcome to KALI Setup"
!define MUI_WELCOMEPAGE_TEXT "KALI — Personal AI Operating System.$\r$\n$\r$\nThis will install KALI on your computer. Click Next to continue."
!define MUI_FINISHPAGE_RUN "$INSTDIR\kali-desktop.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch KALI"

; --- Pages ---
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Russian"

; --- Install ---
Section "Install"
    SetOutPath "$INSTDIR"

    ; Main executables
    File "..\dist\kali-backend.exe"
    File "..\src-tauri\target\release\kali-desktop.exe"

    ; Config
    SetOutPath "$INSTDIR\config"
    File "..\config\kali.yaml"

    ; Agents
    SetOutPath "$INSTDIR\agents"
    File /r "..\agents\*.*"

    ; Create data directories
    CreateDirectory "$INSTDIR\data"
    CreateDirectory "$INSTDIR\data\agents"
    CreateDirectory "$INSTDIR\models"

    ; Desktop shortcut
    CreateShortCut "$DESKTOP\KALI.lnk" "$INSTDIR\kali-desktop.exe" "" "$INSTDIR\kali-desktop.exe"

    ; Start menu
    CreateDirectory "$SMPROGRAMS\KALI"
    CreateShortCut "$SMPROGRAMS\KALI\KALI.lnk" "$INSTDIR\kali-desktop.exe"
    CreateShortCut "$SMPROGRAMS\KALI\Uninstall.lnk" "$INSTDIR\uninstall.exe"

    ; Uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; Registry (for Add/Remove Programs)
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI" "DisplayName" "KALI"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI" "DisplayIcon" "$INSTDIR\kali-desktop.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI" "Publisher" "KALI Team"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI" "DisplayVersion" "0.1.0"
SectionEnd

; --- Uninstall ---
Section "Uninstall"
    Delete "$INSTDIR\kali-backend.exe"
    Delete "$INSTDIR\kali-desktop.exe"
    Delete "$INSTDIR\uninstall.exe"
    Delete "$DESKTOP\KALI.lnk"

    RMDir /r "$INSTDIR\config"
    RMDir /r "$INSTDIR\agents"
    RMDir /r "$INSTDIR\data"
    RMDir /r "$SMPROGRAMS\KALI"
    RMDir "$INSTDIR"

    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI"
SectionEnd
