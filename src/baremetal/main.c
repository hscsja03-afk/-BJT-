/* Standalone Cortex-A9 command service, entirely linked into low OCM.
 * UART: C <seq> <op> <a0> <a1> <a2> <a3> <crc32>\n (decimal).
 * Reply: R <seq> <status> <count> <crc32>\n, then D <index> <up to16 hex words>.
 * CRC32 covers little-endian request words / response header words + payload.
 * JTAG mailbox offers the same operations without a UART dependency.
 */
#include "adda.h"
#include "timebase.h"
#include "xil_cache.h"
#include "xil_io.h"
#include "xgpiops.h"
#include "xuartps.h"
#include "xparameters.h"
#include "xiltimer.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef XPAR_PS7_DDR_0_BASEADDRESS
#error "Build with the DDR-disabled BSP"
#endif
#ifndef ADDA_ENABLED
#define ADDA_ENABLED 0
#endif
#ifndef BJT_BUILD_ID
#error "Build identity must be supplied by build.ps1"
#endif

typedef struct {
    uint32_t magic,abi,capability,heartbeat,request_seq,response_seq,op,args[4];
    uint32_t status,count,crc,payload[BJT_PAYLOAD_WORDS];
} Mailbox;
volatile Mailbox bjt_mailbox={.magic=0x424a5431,.abi=1,.capability=ADDA_ENABLED};
static uint32_t response[BJT_PAYLOAD_WORDS];
static volatile uint32_t ocm_scratch[1024];
static XGpioPs gpio;
static XUartPs uart;
static uint64_t last_command;
static unsigned transport_fault;
extern char _end;

uint32_t hal_read(uint32_t offset){return Xil_In32(0x43c00000U+offset);}
void hal_write(uint32_t offset,uint32_t value){Xil_Out32(0x43c00000U+offset,value);__asm__ volatile("dsb sy":::"memory");}
uint64_t hal_us(void){XTime now;XTime_GetTime(&now);return bjt_ticks_to_us(now,COUNTS_PER_SECOND);}
void hal_delay(unsigned us){uint64_t end=hal_us()+us;while(hal_us()<end){} }
void hal_pin(unsigned pin,unsigned value){XGpioPs_WritePin(&gpio,pin,value);}
unsigned hal_sense(unsigned pin){return XGpioPs_ReadPin(&gpio,pin);}
void hal_output(unsigned pin,unsigned enabled){
    XGpioPs_SetOutputEnablePin(&gpio,pin,enabled);
    XGpioPs_SetDirectionPin(&gpio,pin,enabled);
}
int hal_gpio_init(void){
    static const unsigned pins[]={7,8,9,10,11,12,13,29,30,31,32,33};
    static const unsigned outputs[]={32,33,10,13,31,7,8,11,12,29,30};
    for(unsigned i=0;i<12;i++){
        unsigned pin=pins[i];uint32_t v=Xil_In32(0xf8000700+4*pin);
        if((v&0xfe) || ((v>>9)&7)!=(pin<16?3U:1U))return BJT_GPIO;
    }
    XGpioPs_Config *cfg=XGpioPs_LookupConfig(XPAR_XGPIOPS_0_BASEADDR);
    if(!cfg || XGpioPs_CfgInitialize(&gpio,cfg,cfg->BaseAddr))return BJT_GPIO;
    for(unsigned i=0;i<12;i++)hal_output(pins[i],0);
    for(unsigned i=0;i<11;i++){
        unsigned pin=outputs[i],high=pin==32 || pin==33 || pin==10 || pin==13 || pin==31;
        hal_pin(pin,high);hal_output(pin,1);
    }
    return 0;
}
static uint32_t crc_word(uint32_t crc,uint32_t value){
    for(unsigned byte=0;byte<4;byte++){
        crc^=(value>>(8*byte))&255;
        for(unsigned bit=0;bit<8;bit++)crc=(crc>>1)^((crc&1)?0xedb88320U:0);
    }
    return crc;
}
static uint32_t reply_crc(unsigned seq,unsigned status,unsigned count){
    uint32_t crc=crc_word(crc_word(crc_word(~0U,seq),status),count);
    for(unsigned i=0;i<count;i++)crc=crc_word(crc,response[i]);
    return ~crc;
}
static int execute(unsigned op,const uint32_t args[4],unsigned *count){
    *count=0;last_command=hal_us();
    if(op==CMD_PING){
        response[0]=1;response[1]=ADDA_ENABLED;response[2]=0;
        response[3]=(uint32_t)(uintptr_t)&_end;response[4]=50000000;
        response[5]=transport_fault;response[6]=BJT_BUILD_ID;*count=7;return 0;
    }
    if(op==CMD_OCM_TEST){
        unsigned errors=0;
        for(unsigned pass=0;pass<4;pass++){
            for(unsigned i=0;i<1024;i++)ocm_scratch[i]=((i*0x9e3779b9U)^0xa55a3cc3U)^(pass&1?~0U:0);
            __asm__ volatile("dsb sy":::"memory");
            for(unsigned i=0;i<1024;i++)errors+=ocm_scratch[i]!=(((i*0x9e3779b9U)^0xa55a3cc3U)^(pass&1?~0U:0));
        }
        response[0]=4096;response[1]=errors;response[2]=(uint32_t)(uintptr_t)ocm_scratch;
        *count=3;return errors?BJT_READBACK:0;
    }
    if(!ADDA_ENABLED)return BJT_DISABLED;
    if(op<CMD_INIT || op>CMD_STOP)return BJT_ARGUMENT;
    int rc=adda_command(op,args,response,count);
    if(rc && op!=CMD_INIT && op!=CMD_STOP && rc!=BJT_ARGUMENT){
        /* A peripheral failure invalidates the session and quiesces outputs. */
        response[0]=(uint32_t)adda_stop();*count=1;
    }
    return rc;
}
static int put_char(char c){
    uint64_t end=hal_us()+100000;
    while(XUartPs_IsTransmitFull(XPAR_XUARTPS_0_BASEADDR))
        if(hal_us()>=end){transport_fault=1;return 0;}
    Xil_Out32(XPAR_XUARTPS_0_BASEADDR+XUARTPS_FIFO_OFFSET,(unsigned char)c);return 1;
}
static int put_text(const char *s){while(*s)if(!put_char(*s++))return 0;return 1;}
static void uart_reply(unsigned seq,unsigned status,unsigned count){
    char line[200];
    snprintf(line,sizeof(line),"R %lu %lu %lu %lu\n",(unsigned long)seq,
        (unsigned long)status,(unsigned long)count,(unsigned long)reply_crc(seq,status,count));
    if(!put_text(line))return;
    for(unsigned i=0;i<count;i+=16){
        int used=snprintf(line,sizeof(line),"D %lu",(unsigned long)i);
        for(unsigned j=i;j<count && j<i+16;j++)
            used+=snprintf(line+used,sizeof(line)-(unsigned)used," %08lx",(unsigned long)response[j]);
        line[used++]='\n';line[used]=0;if(!put_text(line))return;
    }
}
static void uart_line(char *line){
    uint32_t request[7];char *p=line;
    if(p[0]!='C' || p[1]!=' ')return;
    p+=2;
    for(unsigned i=0;i<7;i++){
        while(*p==' ')p++;
        if(*p<'0' || *p>'9')return;
        char *end;errno=0;unsigned long value=strtoul(p,&end,10);
        if(errno || end==p || value>UINT32_MAX)return;
        request[i]=(uint32_t)value;p=end;
        if(i<6 && *p!=' ')return;
    }
    while(*p==' ')p++;
    if(*p)return;
    uint32_t crc=~0U;for(unsigned i=0;i<6;i++)crc=crc_word(crc,request[i]);
    if((~crc)!=request[6]){uart_reply(request[0],BJT_ARGUMENT,0);return;}
    unsigned count,status=(unsigned)execute(request[1],request+2,&count);
    uart_reply(request[0],status,count);
    if(transport_fault && ADDA_ENABLED)(void)adda_stop();
}
int main(void){
    Xil_DCacheDisable();Xil_ICacheDisable();
    XUartPs_Config *cfg=XUartPs_LookupConfig(XPAR_XUARTPS_0_BASEADDR);
    if(!cfg || XUartPs_CfgInitialize(&uart,cfg,cfg->BaseAddress) ||
       XUartPs_SetBaudRate(&uart,115200))transport_fault=1;
    last_command=hal_us();
    char line[160];unsigned used=0,discard=0;
    for(;;){
        bjt_mailbox.heartbeat++;
        if(bjt_mailbox.request_seq!=bjt_mailbox.response_seq){
            __asm__ volatile("dmb sy":::"memory");
            uint32_t seq=bjt_mailbox.request_seq,args[4];
            for(unsigned i=0;i<4;i++)args[i]=bjt_mailbox.args[i];
            unsigned count,status=(unsigned)execute(bjt_mailbox.op,args,&count);
            for(unsigned i=0;i<count;i++)bjt_mailbox.payload[i]=response[i];
            bjt_mailbox.count=count;bjt_mailbox.status=status;bjt_mailbox.crc=reply_crc(seq,status,count);
            __asm__ volatile("dmb sy":::"memory");bjt_mailbox.response_seq=seq;
        }
        if(XUartPs_IsReceiveData(XPAR_XUARTPS_0_BASEADDR)){
            char c=(char)Xil_In32(XPAR_XUARTPS_0_BASEADDR+XUARTPS_FIFO_OFFSET);
            if(c=='\n'){
                if(!discard){line[used]=0;uart_line(line);}used=discard=0;
            }else if(c!='\r'){
                if(used+1<sizeof(line))line[used++]=c;else discard=1;
            }
        }
        /* Idle communications cannot leave analog outputs enabled indefinitely. */
        if(ADDA_ENABLED && hal_us()-last_command>10000000){
            (void)adda_stop();last_command=hal_us();
        }
    }
}
