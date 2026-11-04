/* Temporary OCM diagnostic: DDR writes are volatile; eMMC content is read only.
 * No PL download, QSPI access, erase, block write or permanent eMMC switch.
 */
#include "xparameters.h"
#include "xil_cache.h"
#include "xil_printf.h"
#include "xsdps.h"
#include "xsdps_core.h"
#include "xstatus.h"
#include <stdint.h>

typedef struct {
    uint32_t magic, version, phase, result, ddr_errors, card_status;
    uint32_t sectors, card_type, cid[4], sector0_crc, ext_csd_reset_function;
    uint32_t blocked_switches;
    uint32_t region_errors[4], first_bad_address[4], first_expected[4], first_actual[4];
} probe_result;
volatile probe_result boot_probe_result = {.magic=0x42505431U, .version=2};
static XSdPs card;
static unsigned char ext_csd[512] __attribute__((aligned(32)));
static unsigned char sector0[512] __attribute__((aligned(32)));

/* The stock 2026.1 mode initializer enables the permanent RST_N_FUNCTION bit.
 * Replace that stage with reading EXT_CSD in default one-bit mode. */
s32 __wrap_XSdPs_EmmcModeInit(XSdPs *instance) {
    s32 status = XSdPs_Get_Mmc_ExtCsd(instance, ext_csd);
    if (status != XST_SUCCESS) return status;
    instance->BusWidth = XSDPS_1_BIT_WIDTH;
    instance->Mode = XSDPS_DEFAULT_SPEED_MODE;
    instance->SectorCount = (uint32_t)ext_csd[212] | ((uint32_t)ext_csd[213]<<8) |
        ((uint32_t)ext_csd[214]<<16) | ((uint32_t)ext_csd[215]<<24);
    boot_probe_result.ext_csd_reset_function = ext_csd[162];
    return XST_SUCCESS;
}

/* Zynq-7000's v2 host identifies soldered eMMC as MMC. Use the same conservative
 * read-only mode stage rather than the generic legacy MMC speed switch. */
s32 __wrap_XSdPs_MmcModeInit(XSdPs *instance) {
    return __wrap_XSdPs_EmmcModeInit(instance);
}

s32 __wrap_XSdPs_Set_Mmc_ExtCsd(XSdPs *instance, u32 argument) {
    (void)instance; (void)argument;
    boot_probe_result.blocked_switches++;
    return XST_FAILURE;
}

static uint32_t crc32(const unsigned char *data, unsigned length) {
    uint32_t crc=0xffffffffU;
    for(unsigned i=0;i<length;i++) {
        crc ^= data[i];
        for(unsigned b=0;b<8;b++) crc=(crc>>1)^((0U-(crc&1U))&0xedb88320U);
    }
    return ~crc;
}

static unsigned ddr_check(void) {
    const uintptr_t regions[]={0x01000000U,0x11000000U,0x21000000U,0x31000000U};
    unsigned errors=0;
    /* Write all regions before reading to expose aliases between capacities. */
    for(unsigned k=0;k<4;k++) {
        volatile uint32_t *p=(volatile uint32_t *)regions[k];
        for(unsigned i=0;i<16384;i++) p[i]=(uint32_t)(regions[k]+4U*i)^0xa53cc35aU;
    }
    for(unsigned k=0;k<4;k++) {
        volatile uint32_t *p=(volatile uint32_t *)regions[k];
        for(unsigned i=0;i<16384;i++) {
            uint32_t expected=(uint32_t)(regions[k]+4U*i)^0xa53cc35aU,actual=p[i];
            if(actual!=expected) {
                if(!boot_probe_result.region_errors[k]) {
                    boot_probe_result.first_bad_address[k]=(uint32_t)(regions[k]+4U*i);
                    boot_probe_result.first_expected[k]=expected;
                    boot_probe_result.first_actual[k]=actual;
                }
                boot_probe_result.region_errors[k]++; errors++;
            }
        }
        xil_printf("DDR_REGION %08x errors=%u first=%08x expected=%08x actual=%08x\r\n",
            regions[k],boot_probe_result.region_errors[k],boot_probe_result.first_bad_address[k],
            boot_probe_result.first_expected[k],boot_probe_result.first_actual[k]);
    }
    return errors;
}

int main(void) {
    Xil_DCacheDisable(); Xil_ICacheDisable();
    xil_printf("\r\nBOOT_PROBE_V1 OCM, DDR test, READ-ONLY eMMC\r\n");
    boot_probe_result.phase=1;
    boot_probe_result.ddr_errors=ddr_check();
    xil_printf("DDR four 64KiB regions across 1GiB: errors=%u\r\n",boot_probe_result.ddr_errors);
    if(boot_probe_result.ddr_errors) boot_probe_result.result=1;
    boot_probe_result.phase=2;
    XSdPs_Config *cfg=XSdPs_LookupConfig(XPAR_XSDPS_0_BASEADDR);
    if(!cfg) {boot_probe_result.result=2;goto finish;}
    int status=XSdPs_CfgInitialize(&card,cfg,cfg->BaseAddress);
    boot_probe_result.card_status=(uint32_t)status;
    if(status!=XST_SUCCESS) {boot_probe_result.result=3;goto finish;}
    boot_probe_result.phase=3;
    status=XSdPs_CardInitialize(&card);
    boot_probe_result.card_status=(uint32_t)status;
    if(status!=XST_SUCCESS) {boot_probe_result.result=4;goto finish;}
    boot_probe_result.phase=4;
    boot_probe_result.card_type=card.CardType;
    boot_probe_result.sectors=card.SectorCount;
    for(unsigned i=0;i<4;i++) boot_probe_result.cid[i]=card.CardID[i];
    xil_printf("eMMC type=%u sectors=%u CID=%08x %08x %08x %08x\r\n",
        card.CardType,card.SectorCount,card.CardID[0],card.CardID[1],card.CardID[2],card.CardID[3]);
    status=XSdPs_ReadPolled(&card,0,1,sector0);
    boot_probe_result.card_status=(uint32_t)status;
    if(status!=XST_SUCCESS) {boot_probe_result.result=5;goto finish;}
    boot_probe_result.sector0_crc=crc32(sector0,sizeof sector0);
    xil_printf("sector0 read CRC32=%08x; signature=%02x%02x; RESET_FUNC=%u; blocked_switches=%u\r\n",
        boot_probe_result.sector0_crc,sector0[510],sector0[511],
        boot_probe_result.ext_csd_reset_function,boot_probe_result.blocked_switches);
    boot_probe_result.phase=5;
finish:
    xil_printf("BOOT_PROBE_DONE result=%u phase=%u\r\n",boot_probe_result.result,boot_probe_result.phase);
    for(;;) __asm__ volatile("wfi");
}
