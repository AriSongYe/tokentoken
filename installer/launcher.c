#include <windows.h>
#include <wchar.h>
int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, PWSTR cmd, int show) {
    wchar_t dir[MAX_PATH], exe[MAX_PATH + 64], line[3 * MAX_PATH + 64];
    DWORD n = GetModuleFileNameW(NULL, dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return 1;
    wchar_t *s = wcsrchr(dir, L'\\');
    if (s) *s = 0;
    _snwprintf(exe, MAX_PATH + 64, L"%ls\\runtime\\pythonw.exe", dir);
    _snwprintf(line, 3 * MAX_PATH + 64, L"\"%ls\" -I \"%ls\\app\\tokenmon.pyw\"", exe, dir);
    STARTUPINFOW si; PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si)); si.cb = sizeof(si);
    if (!CreateProcessW(exe, line, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        DWORD err = GetLastError();
        wchar_t msg[MAX_PATH + 256];
        if (GetFileAttributesW(exe) == INVALID_FILE_ATTRIBUTES)
            _snwprintf(msg, MAX_PATH + 256, L"TokenToken 실행 파일(runtime\\pythonw.exe)을 찾을 수 없습니다.\n"
                       L"Claude / Codex를 종료한 뒤 설치 프로그램을 다시 실행해 주세요.");
        else
            _snwprintf(msg, MAX_PATH + 256, L"TokenToken을 실행하지 못했습니다 (오류 코드 %lu).\n"
                       L"보안 프로그램이 runtime\\pythonw.exe 실행을 막았을 수 있습니다.", err);
        MessageBoxW(NULL, msg, L"TokenToken", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return 0;
}
