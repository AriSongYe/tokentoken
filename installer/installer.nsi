Unicode true
ManifestDPIAware true
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!define APP "TokenToken"
!define VERSION "1.4.0"
; bump RUNTIME_ID whenever build_installer.sh switches to a different Python build
!define RUNTIME_ID "cpython-3.12.11+20250612"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"
!define RUN_KEY "Software\Microsoft\Windows\CurrentVersion\Run"

Name "${APP}"
OutFile "TokenToken-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "${UNINST_KEY}" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "${APP} ${VERSION}"
VIProductVersion "1.4.0.0"
VIAddVersionKey /LANG=1042 "ProductName" "${APP}"
VIAddVersionKey /LANG=1042 "FileDescription" "${APP} 설치 프로그램"
VIAddVersionKey /LANG=1042 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1042 "ProductVersion" "${VERSION}"

!define MUI_ICON "tokentoken.ico"
!define MUI_UNICON "tokentoken.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "Claude와 Codex의 토큰 사용량과 구독 한도를 항상 위에 떠 있는 작은 창으로 보여주는 프로그램입니다.$\r$\n$\r$\n관리자 권한 없이 현재 사용자 계정에 설치됩니다."
!define MUI_FINISHPAGE_RUN "$INSTDIR\TokenToken.exe"
!define MUI_FINISHPAGE_RUN_TEXT "TokenToken 지금 실행"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Korean"

!macro StopApp
  StrCpy $R9 0
  ${Do}
    FindWindow $R8 "TkTopLevel" "TokenToken"
    ${If} $R8 == 0
      ${Break}
    ${EndIf}
    SendMessage $R8 ${WM_CLOSE} 0 0
    Sleep 400
    IntOp $R9 $R9 + 1
  ${LoopUntil} $R9 >= 10
  nsExec::Exec `powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Process pythonw,python -EA 0 | Where-Object { $$_.Path -like '$INSTDIR\runtime\*' } | Stop-Process -Force"`
  Sleep 500
!macroend

; $0 = 1 when the installed runtime is complete and matches RUNTIME_ID (then it is left alone,
; so an MCP server that keeps runtime\python.exe busy can't break an upgrade)
Function RuntimeIsCurrent
  StrCpy $0 0
  IfFileExists "$INSTDIR\runtime\pythonw.exe" 0 rt_done
  IfFileExists "$INSTDIR\runtime\python312.dll" 0 rt_done
  IfFileExists "$INSTDIR\runtime\Lib\os.py" 0 rt_done
  IfFileExists "$INSTDIR\runtime\Lib\tkinter\__init__.py" 0 rt_done
  ClearErrors
  FileOpen $1 "$INSTDIR\runtime\runtime.id" r
  IfErrors rt_done
  FileRead $1 $2
  FileClose $1
  StrCmp $2 "${RUNTIME_ID}" 0 rt_done
  StrCpy $0 1
rt_done:
FunctionEnd

Section "TokenToken (필수)" SecCore
  SectionIn RO
  !insertmacro StopApp
  SetOutPath "$INSTDIR"
  File "TokenToken.exe"
  File "tokentoken.ico"
  RMDir /r "$INSTDIR\app"
  SetOutPath "$INSTDIR\app"
  File /r "app\*.*"

  Call RuntimeIsCurrent
  ${If} $0 != 1
    ${Do}
      RMDir /r "$INSTDIR\runtime"
      ${IfNot} ${FileExists} "$INSTDIR\runtime\*.*"
        ${Break}
      ${EndIf}
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "TokenToken 런타임 파일이 사용 중이라 교체할 수 없습니다.$\r$\n$\r$\nClaude 데스크톱 앱, Claude Code, Codex가 TokenToken MCP 서버를 실행하고 있을 수 있습니다. 이 프로그램들을 모두 종료한 뒤 [다시 시도]를 누르세요." IDRETRY rt_retry
      Abort "런타임 파일이 사용 중이라 설치를 중단했습니다."
    rt_retry:
      !insertmacro StopApp
    ${Loop}
    SetOutPath "$INSTDIR\runtime"
    File /r "runtime\*.*"
    FileOpen $1 "$INSTDIR\runtime\runtime.id" w
    FileWrite $1 "${RUNTIME_ID}"
    FileClose $1
  ${EndIf}
  SetOutPath "$INSTDIR"

  CreateShortcut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\TokenToken.exe" "" "$INSTDIR\tokentoken.ico"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${APP}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\tokentoken.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" $0
SectionEnd

Section "Windows 시작 시 자동 실행" SecAuto
  WriteRegStr HKCU "${RUN_KEY}" "${APP}" '"$INSTDIR\TokenToken.exe"'
  Delete "$SMSTARTUP\TokenToken.vbs"
SectionEnd

Section "바탕화면 바로가기" SecDesk
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\TokenToken.exe" "" "$INSTDIR\tokentoken.ico"
SectionEnd

Section "MCP 서버 등록 (Claude Code / Codex / Claude Desktop)" SecMcp
  nsExec::Exec `"$INSTDIR\runtime\python.exe" -I "$INSTDIR\app\install_mcp.py" --no-pause`
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} "위젯 프로그램과 실행에 필요한 파이썬 런타임입니다. 따로 Python을 설치할 필요가 없습니다."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecAuto} "로그인하면 TokenToken이 자동으로 실행됩니다. 나중에 위젯 우클릭 메뉴에서 끌 수 있습니다."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesk} "바탕화면에 바로가기를 만듭니다."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMcp} "Claude나 Codex에서 '내 토큰 사용량 알려줘'라고 물을 수 있도록 MCP 서버를 등록합니다."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  !insertmacro StopApp
  nsExec::Exec `"$INSTDIR\runtime\python.exe" -I "$INSTDIR\app\install_mcp.py" --remove --no-pause`
  DeleteRegValue HKCU "${RUN_KEY}" "${APP}"
  DeleteRegKey HKCU "${UNINST_KEY}"
  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\TokenToken.exe"
  Delete "$INSTDIR\tokentoken.ico"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd
