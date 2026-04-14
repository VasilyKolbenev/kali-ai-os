; KALI Installer Script (NSIS)
; Builds: KALI-Setup-0.1.0.exe
;
; Prerequisites: NSIS installed (winget install NSIS.NSIS)
; Build: cd scripts && "C:\Program Files (x86)\NSIS\makensis.exe" installer.nsi

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

    ; === Check and install WebView2 Runtime ===
    DetailPrint "Checking Microsoft Edge WebView2 Runtime..."

    ; Check if WebView2 is installed (registry)
    ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BEB-E15CD01B5714}" "pv"
    ${If} $0 == ""
        ReadRegStr $0 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BEB-E15CD01B5714}" "pv"
    ${EndIf}

    ${If} $0 == ""
        DetailPrint "WebView2 not found. Downloading and installing..."

        ; Download WebView2 bootstrapper (small ~2MB, downloads the rest)
        NSISdl::download "https://go.microsoft.com/fwlink/p/?LinkId=2124703" "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        Pop $0
        ${If} $0 == "success"
            DetailPrint "Installing WebView2 Runtime..."
            ExecWait '"$TEMP\MicrosoftEdgeWebview2Setup.exe" /silent /install' $0
            DetailPrint "WebView2 installed (exit code: $0)"
            Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        ${Else}
            DetailPrint "WARNING: Failed to download WebView2. KALI may not work without it."
            DetailPrint "Please install manually: https://developer.microsoft.com/en-us/microsoft-edge/webview2/"
            MessageBox MB_OK|MB_ICONEXCLAMATION "Could not download WebView2 Runtime.$\r$\n$\r$\nPlease install it manually from:$\r$\nhttps://developer.microsoft.com/en-us/microsoft-edge/webview2/$\r$\n$\r$\nKALI requires WebView2 to run."
        ${EndIf}
    ${Else}
        DetailPrint "WebView2 found (version: $0)"
    ${EndIf}

    ; === Main executables ===
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
