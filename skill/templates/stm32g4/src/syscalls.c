/* syscalls.c - the newlib hooks the C library's exit path references.
 * No file I/O here (the console writes USART1 directly); defining them
 * replaces libnosys's versions, which warn at link time. */
#include <errno.h>

int _close(int fd);
int _lseek(int fd, int off, int whence);
int _read(int fd, char *buf, int len);
int _write(int fd, const char *buf, int len);

int _close(int fd) { (void)fd; errno = EBADF; return -1; }
int _lseek(int fd, int off, int whence) { (void)fd; (void)off; (void)whence; return 0; }
int _read(int fd, char *buf, int len) { (void)fd; (void)buf; (void)len; return 0; }
int _write(int fd, const char *buf, int len) { (void)fd; (void)buf; return len; }
