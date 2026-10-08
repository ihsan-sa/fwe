/* check.h - tiny host test harness. Each test file has its own main() and
 * ends with CHECK_DONE(), which exits nonzero when any check failed. */
#ifndef CHECK_H
#define CHECK_H

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static int check_failures;
static int check_count;

#define CHECK(cond) do { check_count++; if (!(cond)) { check_failures++; \
    printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); } } while (0)

#define CHECK_NEAR(a, b, tol) do { double a_ = (a), b_ = (b); check_count++; \
    if (!(fabs(a_ - b_) <= (tol))) { check_failures++; \
    printf("FAIL %s:%d: %s = %.6f, want %.6f +- %g\n", __FILE__, __LINE__, #a, a_, b_, (double)(tol)); } \
    } while (0)

#define CHECK_EQ(a, b) do { long long a_ = (long long)(a), b_ = (long long)(b); check_count++; \
    if (a_ != b_) { check_failures++; \
    printf("FAIL %s:%d: %s = %lld, want %lld\n", __FILE__, __LINE__, #a, a_, b_); } } while (0)

#define CHECK_DONE() do { printf("%s: %d checks, %d failed\n", __FILE__, check_count, check_failures); \
    return check_failures ? EXIT_FAILURE : EXIT_SUCCESS; } while (0)

#endif
