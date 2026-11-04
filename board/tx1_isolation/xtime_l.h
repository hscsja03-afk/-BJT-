#ifndef TX1_ISOLATION_TIME_H
#define TX1_ISOLATION_TIME_H
#include <stdint.h>
#include "xil_io.h"
#include "xparameters.h"
typedef uint64_t XTime;
#define COUNTS_PER_SECOND (XPAR_CPU_CORE_CLOCK_FREQ_HZ / 2U)
static inline void XTime_GetTime(XTime *value) {
    uint32_t a,b,low;
    do {a=Xil_In32(0xf8f00204U);low=Xil_In32(0xf8f00200U);b=Xil_In32(0xf8f00204U);} while(a!=b);
    *value=((uint64_t)a<<32)|low;
}
#endif
