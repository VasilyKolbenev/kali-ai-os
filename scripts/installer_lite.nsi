; KALI Lite Installer — small build for friends & testers
; No local F5-TTS (GPU). Uses ElevenLabs cloud voice (API key required).
; Target: ~300-500 MB installer, fits in Telegram (2 GB).

!include "MUI2.nsh"

Name "KALI (Lite)"
OutFile "..\dist_lite\KALI-Lite-Setup-0.1.0.exe"
InstallDir "$PROGRAMFILES64\KALI"
RequestExecutionLevel admin

!define MUI_ICON "..\src-tauri\icons\icon.ico"
!define MUI_UNICON "..\src-tauri\icons\icon.ico"
!define MUI_WELCOMEPAGE_TITLE "Welcome to KALI (Lite)"
!define MUI_WELCOMEPAGE_TEXT "KALI — Personal AI Operating System.$\r$\n$\r$\nLite build uses ElevenLabs cloud voice. You'll need an API key (set in Settings after install).$\r$\n$\r$\nClick Next to continue."
!define MUI_FINISHPAGE_RUN "$INSTDIR\kali-desktop.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch KALI"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Russian"

Section "Install"
    SetOutPath "$INSTDIR"

    ; WebView2 check
    ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BEB-E15CD01B5714}" "pv"
    ${If} $0 == ""
        ReadRegStr $0 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BEB-E15CD01B5714}" "pv"
    ${EndIf}
    ${If} $0 == ""
        DetailPrint "WebView2 not found. Downloading..."
        NSISdl::download "https://go.microsoft.com/fwlink/p/?LinkId=2124703" "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        Pop $0
        ${If} $0 == "success"
            ExecWait '"$TEMP\MicrosoftEdgeWebview2Setup.exe" /silent /install' $0
            Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        ${EndIf}
    ${EndIf}

    ; Main executables (onedir: backend is a folder)
    File /r "..\dist_lite\kali-backend\*.*"
    File "..\src-tauri\target\release\kali-desktop.exe"

    SetOutPath "$INSTDIR\config"
    File "..\config\kali.yaml"

    SetOutPath "$INSTDIR\agents"
    File /r "..\agents\*.*"

    SetOutPath "$INSTDIR\resources\sounds\ru"
    File /r "..\resources\sounds\ru\*.*"
    SetOutPath "$INSTDIR\resources\sounds\en"
    File /r "..\resources\sounds\en\*.*"

    ; ElevenLabs reference clips (ASCII-named, PCM_16 mono, ready for /voice/clone)
    SetOutPath "$INSTDIR\models\elevenlabs_ref"
    File /r "..\models\elevenlabs_ref\*.wav"

    SetOutPath "$INSTDIR"
    CreateDirectory "$APPDATA\KALI"
    CreateDirectory "$APPDATA\KALI\logs"

    ; Shortcuts
    CreateShortCut "$DESKTOP\KALI.lnk" "$INSTDIR\kali-desktop.exe" "" "$INSTDIR\kali-desktop.exe"
    CreateDirectory "$SMPROGRAMS\KALI"
    CreateShortCut "$SMPROGRAMS\KALI\KALI.lnk" "$INSTDIR\kali-desktop.exe"
    CreateShortCut "$SMPROGRAMS\KALI\Uninstall.lnk" "$INSTDIR\uninstall.exe"

    WriteUninstaller "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI" "DisplayName" "KALI (Lite)"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI" "DisplayIcon" "$INSTDIR\kali-desktop.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI" "Publisher" "KALI Team"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI" "DisplayVersion" "0.1.0-lite"
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\kali-desktop.exe"
    Delete "$INSTDIR\uninstall.exe"
    Delete "$DESKTOP\KALI.lnk"
    RMDir /r "$INSTDIR\config"
    RMDir /r "$INSTDIR\agents"
    RMDir /r "$INSTDIR\resources"
    RMDir /r "$INSTDIR\_internal"
    RMDir /r "$SMPROGRAMS\KALI"
    RMDir "$INSTDIR"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\KALI"
SectionEnd
