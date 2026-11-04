/* Only TX1 MMIO/I2C, UART and timer are touched. PS/PL are kept from the
 * previously working state. Original reference driver is included unchanged. */
#include "xtime_l.h"
#include "xil_cache.h"
#include "xuartps_hw.h"
static unsigned phase_us=2;
void board_delay_us(unsigned us) {
    XTime a,b;unsigned wait=us==2?phase_us:us;
    XTime_GetTime(&a);
    do {XTime_GetTime(&b);} while(b-a<((uint64_t)wait*COUNTS_PER_SECOND+999999U)/1000000U);
}
#include "../../reference/embedded/sw/dac60501.c"

static int migrated(unsigned code) {
    unsigned v;int r;ready=0;wave=0;
    pins(3);half();if(lines()!=3)return TX1_STUCK;
    r=read_reg(1,&v);if(r)return r;if(v!=0x2195)return TX1_ID_ERROR;
    r=verified(3,1);
    if(!r)r=verified(4,0x101);
    if(!r)r=verified(2,0);
    if(!r)r=verified(8,0);
    if(!r)r=read_reg(7,&v);
    if(!r && (v&1))r=TX1_VERIFY;
    if(!r){ready=1;r=verified(8,code<<4);}
    if(!r)r=verified(3,0);
    return r;
}
static int reset_base(void){int r=write_reg(5,0x0a);board_delay_us(1000);if(!r)r=verified(4,0x101);ready=1;return r;}
static int staged(unsigned code){int r=verified(3,1);if(!r)r=verified(4,0x101);if(!r)r=verified(2,0);if(!r)r=verified(8,code<<4);if(!r)r=verified(3,0);ready=1;return r;}
int main(void) {
    XTime last,now;unsigned active=0;
    Xil_DCacheDisable();
    Xil_Out32(0xf8f00208U,Xil_In32(0xf8f00208U)|1U);
    if(Xil_In32(TX1_ID)!=0x54583101U){xil_printf("ISOLATION_BAD_PL\r\n");for(;;){}}
    pins(3);(void)verified(3,1);ready=1;XTime_GetTime(&last);
    xil_printf("TX1_ISOLATION_READY no_other_converter_initialization\r\n");
    for(;;){
        XTime_GetTime(&now);
        if(active && now-last>10ULL*COUNTS_PER_SECOND){(void)verified(3,1);active=0;xil_printf("ISOLATION_AUTO_OFF\r\n");}
        if(!XUartPs_IsReceiveData(0xe0000000U))continue;
        unsigned c=XUartPs_RecvByte(0xe0000000U);int r=0;
        XTime_GetTime(&last);
        switch(c){
        case '?':xil_printf("TX1_ISOLATION_READY commands=B/P/S/Z/C/Q/R\r\n");continue;
        case 'B':phase_us=2;r=initialize();if(!r)r=dc(1638);active=!r;break;
        case 'P':phase_us=2;r=migrated(1638);active=!r;break;
        case 'S':phase_us=100;r=migrated(1638);active=!r;break;
        case 'Z':phase_us=2;r=migrated(0);active=!r;break;
        case 'C':phase_us=2;r=migrated(2000);active=!r;break;
        case 'T':phase_us=2;r=write_reg(5,0x0a);board_delay_us(1000);if(!r)r=verified(4,0x101);ready=1;active=!r;break;
        case 'D':phase_us=2;r=dc(1638);active=!r;break;
        case '0':phase_us=2;r=dc(0);active=!r;break;
        case 'L':r=write_reg(5,0x10);active=!r;break;
        case 'F':r=write_reg(2,0);if(!r)r=dc(1638);active=!r;break;
        case 'X':phase_us=2;r=reset_base();if(!r)r=verified(3,1);if(!r)r=verified(8,0);if(!r)r=verified(8,0x6660);if(!r)r=verified(3,0);active=!r;break;
        case 'Y':phase_us=2;r=reset_base();if(!r)r=verified(3,1);if(!r)r=verified(8,0x6660);if(!r)r=verified(3,0);active=!r;break;
        case 'K':phase_us=2;r=reset_base();if(!r)r=verified(8,0);if(!r)r=verified(3,1);if(!r)r=verified(8,0x6660);if(!r)r=verified(3,0);active=!r;break;
        case 'W':phase_us=2;r=reset_base();if(!r)r=verified(3,1);if(!r)r=verified(8,0x0010);if(!r)r=verified(8,0x6660);if(!r)r=verified(3,0);active=!r;break;
        case 'V':phase_us=2;r=reset_base();if(!r)r=verified(8,0);if(!r)r=verified(3,1);if(!r)r=verified(3,0);if(!r)r=verified(8,0x6660);active=!r;break;
        case 'H':phase_us=2;r=reset_base();if(!r)r=verified(3,1);if(!r)r=verified(8,0x4000);if(!r)r=verified(8,0x6660);if(!r)r=verified(3,0);active=!r;break;
        case 'J':phase_us=2;r=reset_base();if(!r)r=verified(3,1);if(!r)r=verified(3,0);if(!r)r=verified(8,0);if(!r)r=verified(8,0x6660);active=!r;break;
        case 'A':phase_us=2;r=verified(3,1);board_delay_us(1000);if(!r)r=verified(3,0);board_delay_us(1000);if(!r)r=dc(1638);active=!r;break;
        case 'E':phase_us=2;r=verified(3,0);board_delay_us(1000);if(!r)r=dc(1638);active=!r;break;
        case 'N':phase_us=2;r=staged(1638);active=!r;break;
        case 'O':phase_us=2;r=staged(0);active=!r;break;
        case '2':phase_us=2;r=staged(819);active=!r;break;
        case 'Q':r=verified(3,1);active=0;break;
        case 'R':r=status();break;
        default:continue;
        }
        if(r){(void)verified(3,1);active=0;}
        xil_printf("ISOLATION_RESULT command=%c status=%d phase_us=%u active=%u\r\n",c,r,phase_us,active);
    }
}
