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
        MessageBoxW(NULL, L"TokenToken 실행 파일(runtime\\pythonw.exe)을 찾을 수 없습니다.\n다시 설치해 주세요.",
                    L"TokenToken", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return 0;
}
