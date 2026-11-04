/* OCM-only DDR data-lane diagnostic. Volatile DDR writes, no peripherals,
 * PL configuration, QSPI access or eMMC access. Run before booting Linux. */
#include "xil_cache.h"
#include <stdint.h>

typedef struct {
    uint32_t magic, version, complete;
    uint32_t pattern_errors[8], byte_errors[4], xor_mask;
    uint32_t even_errors, odd_errors;
    uint32_t first_bad_address, first_expected, first_actual;
    uint32_t sample_expected[16], sample_first[16], sample_second[16];
} lane_result;
volatile lane_result ddr_lane_result = {.magic=0x44445231U, .version=1};

static uint32_t pattern(unsigned kind, unsigned i) {
    const uint32_t fixed[]={0,0xffffffffU,0x55555555U,0xaaaaaaaaU,
        0x00ff00ffU,0xff00ff00U};
    if(kind<6) return fixed[kind];
    if(kind==6) return (0x01020000U+4U*i)^0xa53cc35aU;
    uint32_t x=(i+1U)*0x9e3779b9U;
    x^=x<<13; x^=x>>17; x^=x<<5;
    return x;
}

int main(void) {
    volatile uint32_t *const memory=(volatile uint32_t *)0x01020000U;
    Xil_DCacheDisable(); Xil_ICacheDisable();
    for(unsigned kind=0;kind<8;kind++) {
        for(unsigned i=0;i<4096;i++) memory[i]=pattern(kind,i);
        __asm__ volatile("dsb sy" ::: "memory");
        for(unsigned pass=0;pass<2;pass++) {
            for(unsigned i=0;i<4096;i++) {
                uint32_t expected=pattern(kind,i),actual=memory[i],diff=expected^actual;
                if(kind==7 && i<16) {
                    ddr_lane_result.sample_expected[i]=expected;
                    if(pass==0) ddr_lane_result.sample_first[i]=actual;
                    else ddr_lane_result.sample_second[i]=actual;
                }
                if(!diff) continue;
                if(!ddr_lane_result.xor_mask) {
                    ddr_lane_result.first_bad_address=0x01020000U+4U*i;
                    ddr_lane_result.first_expected=expected;
                    ddr_lane_result.first_actual=actual;
                }
                ddr_lane_result.xor_mask|=diff;
                ddr_lane_result.pattern_errors[kind]++;
                for(unsigned b=0;b<4;b++)
                    if(diff&(0xffU<<(8U*b))) ddr_lane_result.byte_errors[b]++;
                if(i&1U) ddr_lane_result.odd_errors++;
                else ddr_lane_result.even_errors++;
            }
            __asm__ volatile("dsb sy" ::: "memory");
        }
    }
    ddr_lane_result.complete=1;
    for(;;) __asm__ volatile("wfi");
}
