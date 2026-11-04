#include "timebase.h"
#include <assert.h>
#include <stdio.h>
/* Match the unparenthesized BSP macro that exposed the integration bug. */
#define TEST_COUNTS_PER_SECOND 666666688ULL/2
int main(void) {
    uint64_t hz=TEST_COUNTS_PER_SECOND;
    assert(bjt_ticks_to_us(0,TEST_COUNTS_PER_SECOND)==0);
    assert(bjt_ticks_to_us(hz,TEST_COUNTS_PER_SECOND)==1000000);
    assert(bjt_ticks_to_us(hz/4,TEST_COUNTS_PER_SECOND)==250000);
    assert(bjt_ticks_to_us(hz*86400,TEST_COUNTS_PER_SECOND)==86400000000ULL);
    assert(bjt_ticks_to_us(hz*86400+hz/2,TEST_COUNTS_PER_SECOND)==86400500000ULL);
    puts("C_TIMEBASE_PASS macro_precedence quarter_second one_second twenty_four_hours");
    return 0;
}
