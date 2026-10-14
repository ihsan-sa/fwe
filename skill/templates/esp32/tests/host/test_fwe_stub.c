#include <assert.h>
#include <stdio.h>

#include "fwe_stub.h"

int main(void)
{
    assert(fwe_stub_clamp_mb(-500, -6000, 0) == -500);
    assert(fwe_stub_clamp_mb(300, -6000, 0) == 0);
    assert(fwe_stub_clamp_mb(-9000, -6000, 0) == -6000);
    assert(fwe_stub_clamp_mb(-9000, 0, -6000) == -6000); /* bounds given either way round */
    puts("test_fwe_stub: ok");
    return 0;
}
