#ifndef BJT_TIMEBASE_H
#define BJT_TIMEBASE_H
#include <stdint.h>
/* Passing frequency as an argument prevents macro arithmetic from changing
 * division precedence. Split quotient/remainder to avoid ticks*1e6 overflow. */
static inline uint64_t bjt_ticks_to_us(uint64_t ticks,uint64_t frequency) {
    return (ticks/frequency)*1000000U+((ticks%frequency)*1000000U)/frequency;
}
#endif
