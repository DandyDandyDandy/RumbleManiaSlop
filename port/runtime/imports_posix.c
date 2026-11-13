// POSIX file descriptors used by the lifted il2cpp os layer (open/read/write/stat/...), on Win32 handles.
// Guest structures follow musl/aarch64: struct stat is 128 bytes, struct dirent has d_name at +19.
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

void rt_fs_path(const char *g, wchar_t *out, size_t cap);

#define MAX_FD 1024
static HANDLE g_fd[MAX_FD];
static uint8_t g_fd_append[MAX_FD];
static SRWLOCK g_fd_lock = SRWLOCK_INIT;
static void set_errno(Cpu *c, int e) { *(int *)(((RtThread *)c)->tlr + 0x800) = e; }
static HANDLE fd_handle(uint32_t fd) {
    if (fd == 0) return GetStdHandle(STD_INPUT_HANDLE);
    if (fd == 1) return GetStdHandle(STD_OUTPUT_HANDLE);
    if (fd == 2) return GetStdHandle(STD_ERROR_HANDLE);
    return fd < MAX_FD ? g_fd[fd] : NULL;
}
static int fd_new(HANDLE h, int append) {
    AcquireSRWLockExclusive(&g_fd_lock);
    int fd = -1;
    for (int i = 3; i < MAX_FD; i++)
        if (!g_fd[i]) { g_fd[i] = h; g_fd_append[i] = (uint8_t)append; fd = i; break; }
    ReleaseSRWLockExclusive(&g_fd_lock);
    return fd;
}
static int win_errno(void) {
    switch (GetLastError()) {
    case ERROR_FILE_NOT_FOUND: case ERROR_PATH_NOT_FOUND: case ERROR_INVALID_NAME: case ERROR_BAD_PATHNAME: return 2;   // ENOENT
    case ERROR_ACCESS_DENIED: case ERROR_SHARING_VIOLATION: return 13;                       // EACCES
    case ERROR_FILE_EXISTS: case ERROR_ALREADY_EXISTS: return 17;                            // EEXIST
    case ERROR_DIR_NOT_EMPTY: return 39;
    default: return 5;                                                                       // EIO
    }
}

HOSTFN(open) {
    const char *path = STR(0);
    uint32_t fl = W(1);
    if (!strcmp(path, "/dev/stdin")) { RET(0); return; }
    if (!strcmp(path, "/dev/stdout")) { RET(1); return; }
    if (!strcmp(path, "/dev/stderr")) { RET(2); return; }
    wchar_t w[1024];
    rt_fs_path(path, w, 1024);
    DWORD acc = (fl & 3) == 0 ? GENERIC_READ : (fl & 3) == 1 ? GENERIC_WRITE : GENERIC_READ | GENERIC_WRITE;
    DWORD disp = (fl & 0100) ? ((fl & 0200) ? CREATE_NEW : (fl & 01000) ? CREATE_ALWAYS : OPEN_ALWAYS) : (fl & 01000) ? TRUNCATE_EXISTING : OPEN_EXISTING;
    HANDLE h = CreateFileW(w, acc, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, disp, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_BACKUP_SEMANTICS, NULL);
    if (rt_trace & 8) rt_log("fs: open(%s, %#o) -> %s", path, fl, h == INVALID_HANDLE_VALUE ? "failed" : "ok");
    if (h == INVALID_HANDLE_VALUE) { set_errno(c, win_errno()); RET(-1ll); return; }
    int fd = fd_new(h, (fl & 02000) != 0);
    if (fd < 0) { CloseHandle(h); set_errno(c, 24); }
    RET((int64_t)fd);
}
HOSTFN(close) {
    uint32_t fd = W(0);
    if (fd >= 3 && fd < MAX_FD && g_fd[fd]) { CloseHandle(g_fd[fd]); g_fd[fd] = NULL; }
    RET(0);
}
HOSTFN(read) {
    HANDLE h = fd_handle(W(0));
    DWORD got = 0;
    if (!h || !ReadFile(h, PTR(1), (DWORD)(X(2) > 0x40000000 ? 0x40000000 : X(2)), &got, NULL)) {
        if (GetLastError() == ERROR_HANDLE_EOF || GetLastError() == ERROR_BROKEN_PIPE) { RET(0); return; }
        set_errno(c, 5); RET(-1ll); return;
    }
    RET(got);
}
HOSTFN(write) {
    uint32_t fd = W(0);
    if (fd == 1 || fd == 2) {
        size_t n = X(2);
        const char *s = STR(1);
        while (n && (s[n - 1] == '\n' || s[n - 1] == '\r')) n--;
        if (n) rt_log("guest %s: %.*s", fd == 2 ? "stderr" : "stdout", (int)n, s);
        RET(X(2));
        return;
    }
    HANDLE h = fd_handle(fd);
    DWORD got = 0;
    if (h && fd < MAX_FD && g_fd_append[fd]) SetFilePointer(h, 0, NULL, FILE_END);
    if (!h || !WriteFile(h, PTR(1), (DWORD)X(2), &got, NULL)) { set_errno(c, 5); RET(-1ll); return; }
    RET(got);
}
HOSTFN(lseek) {
    LARGE_INTEGER off, out;
    off.QuadPart = (LONGLONG)X(1);
    HANDLE h = fd_handle(W(0));
    if (!h || !SetFilePointerEx(h, off, &out, W(2) == 0 ? FILE_BEGIN : W(2) == 1 ? FILE_CURRENT : FILE_END)) { set_errno(c, 29); RET(-1ll); return; }
    RET(out.QuadPart);
}
HOSTFN(fsync) { HANDLE h = fd_handle(W(0)); if (h) FlushFileBuffers(h); RET(0); }
HOSTFN(ftruncate) {
    LARGE_INTEGER off, cur, zero = {0};
    HANDLE h = fd_handle(W(0));
    off.QuadPart = (LONGLONG)X(1);
    if (!h) { set_errno(c, 9); RET(-1ll); return; }
    SetFilePointerEx(h, zero, &cur, FILE_CURRENT);
    SetFilePointerEx(h, off, NULL, FILE_BEGIN);
    SetEndOfFile(h);
    SetFilePointerEx(h, cur, NULL, FILE_BEGIN);
    RET(0);
}
static uint64_t ft_sec(FILETIME ft) { return (((uint64_t)ft.dwHighDateTime << 32 | ft.dwLowDateTime) - 116444736000000000ull) / 10000000ull; }
static void fill_stat(uint64_t st, DWORD attrs, uint64_t size, FILETIME at, FILETIME mt, FILETIME ct) {
    memset((void *)(uintptr_t)st, 0, 128);
    ST32(st + 16, (attrs & FILE_ATTRIBUTE_DIRECTORY ? 0040755u : 0100644u) & ((attrs & FILE_ATTRIBUTE_READONLY) ? ~0222u : ~0u));
    ST32(st + 20, 1);
    ST64(st + 48, size);
    ST32(st + 56, 4096);
    ST64(st + 64, (size + 511) / 512);
    ST64(st + 72, ft_sec(at)); ST64(st + 88, ft_sec(mt)); ST64(st + 104, ft_sec(ct));
}
HOSTFN(stat) {
    wchar_t w[1024];
    WIN32_FILE_ATTRIBUTE_DATA fa;
    rt_fs_path(STR(0), w, 1024);
    size_t n = wcslen(w);
    if (n > 3 && w[n - 1] == L'\\') w[n - 1] = 0;
    if (!GetFileAttributesExW(w, GetFileExInfoStandard, &fa)) {
        if (rt_trace & 8) rt_log("fs: stat(%s) -> not found", STR(0));
        set_errno(c, win_errno()); RET(-1ll); return;
    }
    fill_stat(X(1), fa.dwFileAttributes, (uint64_t)fa.nFileSizeHigh << 32 | fa.nFileSizeLow, fa.ftLastAccessTime, fa.ftLastWriteTime, fa.ftCreationTime);
    RET(0);
}
HOSTALIAS(lstat, stat)
HOSTFN(fstat) {
    uint32_t fd = W(0);
    BY_HANDLE_FILE_INFORMATION bi;
    if (fd < 3) { FILETIME z = {0}; fill_stat(X(1), 0, 0, z, z, z); ST32(X(1) + 16, 0020620); RET(0); return; }
    HANDLE h = fd_handle(fd);
    if (!h || !GetFileInformationByHandle(h, &bi)) { set_errno(c, 9); RET(-1ll); return; }
    fill_stat(X(1), bi.dwFileAttributes, (uint64_t)bi.nFileSizeHigh << 32 | bi.nFileSizeLow, bi.ftLastAccessTime, bi.ftLastWriteTime, bi.ftCreationTime);
    RET(0);
}
HOSTFN(access) {
    wchar_t w[1024];
    rt_fs_path(STR(0), w, 1024);
    if (GetFileAttributesW(w) == INVALID_FILE_ATTRIBUTES) { set_errno(c, 2); RET(-1ll); return; }
    RET(0);
}
HOSTFN(mkdir) { wchar_t w[1024]; rt_fs_path(STR(0), w, 1024); if (CreateDirectoryW(w, NULL)) RET(0); else { set_errno(c, win_errno()); RET(-1ll); } }
HOSTFN(rmdir) { wchar_t w[1024]; rt_fs_path(STR(0), w, 1024); if (RemoveDirectoryW(w)) RET(0); else { set_errno(c, win_errno()); RET(-1ll); } }
HOSTFN(unlink) { wchar_t w[1024]; rt_fs_path(STR(0), w, 1024); if (DeleteFileW(w)) RET(0); else { set_errno(c, win_errno()); RET(-1ll); } }
HOSTFN(rename) {
    wchar_t a[1024], b[1024];
    rt_fs_path(STR(0), a, 1024); rt_fs_path(STR(1), b, 1024);
    if (MoveFileExW(a, b, MOVEFILE_REPLACE_EXISTING)) RET(0); else { set_errno(c, win_errno()); RET(-1ll); }
}
HOSTFN(fcntl) { RET(0); }

typedef struct { HANDLE h; WIN32_FIND_DATAW fd; int first, done; uint8_t ent[280]; } GDir;
HOSTFN(opendir) {
    wchar_t w[1040];
    rt_fs_path(STR(0), w, 1024);
    size_t n = wcslen(w);
    if (n && w[n - 1] != L'\\') w[n++] = L'\\';
    w[n++] = L'*'; w[n] = 0;
    GDir *d = calloc(1, sizeof *d);
    d->h = FindFirstFileW(w, &d->fd);
    if (d->h == INVALID_HANDLE_VALUE) { free(d); set_errno(c, win_errno()); RET(0); return; }
    d->first = 1;
    RET(d);
}
HOSTFN(readdir) {
    GDir *d = PTR(0);
    if (!d || d->done) { RET(0); return; }
    if (!d->first && !FindNextFileW(d->h, &d->fd)) { d->done = 1; RET(0); return; }
    d->first = 0;
    memset(d->ent, 0, sizeof d->ent);
    uint64_t e = (uint64_t)(uintptr_t)d->ent;
    ST64(e, 1);
    ST16(e + 16, 280);
    ST8(e + 18, d->fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY ? 4 : 8);   // DT_DIR / DT_REG
    WideCharToMultiByte(CP_UTF8, 0, d->fd.cFileName, -1, (char *)d->ent + 19, 256, NULL, NULL);
    RET(e);
}
HOSTFN(closedir) { GDir *d = PTR(0); if (d) { FindClose(d->h); free(d); } RET(0); }
