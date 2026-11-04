/* Runs the real C driver against a pin-level SPI model on the host.
 * Faults stop initialization at progressively later stages; no board access.
 */
#include "adda.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static const char *fault;
static uint64_t ticks;
static unsigned pins[54],direction[54],registers[2][8192],adc[8192];
static unsigned cs=99,spi_bits,spi_bytes[3],adc_bits,adc_bytes[3],gpio_calls,pl_writes;
static unsigned capture_started;
uint64_t hal_us(void){ticks+=10;return ticks;}
void hal_delay(unsigned us){ticks+=us;}
void hal_output(unsigned pin,unsigned enabled){direction[pin]=enabled;}
int hal_gpio_init(void){
    gpio_calls++;
    if(!strcmp(fault,"gpio"))return BJT_GPIO;
    pins[10]=pins[13]=pins[31]=pins[32]=pins[33]=1;
    direction[29]=1;return 0;
}
static unsigned address(void){return cs==10?(spi_bytes[0]&31):((spi_bytes[0]&31)<<8)|spi_bytes[1];}
void hal_pin(unsigned pin,unsigned value){
    unsigned previous=pins[pin];pins[pin]=value;
    if((pin==10 || pin==13) && !value && previous){cs=pin;spi_bits=0;memset(spi_bytes,0,sizeof(spi_bytes));}
    if((pin==10 || pin==13) && value && !previous && cs==pin){
        unsigned needed=cs==10?16:24;
        if(spi_bits==needed && !(spi_bytes[0]&128)){
            unsigned a=address(),v=spi_bytes[cs==10?1:2];
            registers[cs==10?0:1][a]=v;
            if(cs==10 && a==3)assert(v==0x33); /* no analog enable in failed init */
        }
        cs=99;
    }
    if(pin==7 && value && !previous && cs!=99){
        if(spi_bits<24)spi_bytes[spi_bits/8]=(spi_bytes[spi_bits/8]<<1)|pins[8];
        spi_bits++;
    }
    if(pin==31 && !value && previous){adc_bits=0;memset(adc_bytes,0,sizeof(adc_bytes));}
    if(pin==30 && value && !previous && !pins[31]){
        if(adc_bits<24)adc_bytes[adc_bits/8]=(adc_bytes[adc_bits/8]<<1)|pins[29];
        adc_bits++;
    }
    if(pin==31 && value && !previous && adc_bits==24 && !(adc_bytes[0]&128)){
        unsigned a=((adc_bytes[0]&31)<<8)|adc_bytes[1];adc[a]=adc_bytes[2];
    }
}
unsigned hal_sense(unsigned pin){
    if(pin==9 && cs!=99){
        if(cs==10 && spi_bits>8 && (spi_bytes[0]&128)){
            if(!strcmp(fault,"dac"))return 0;
            return (registers[0][address()]>>(7-((spi_bits-9)%8)))&1;
        }
        if(cs==13 && spi_bits>=16 && (spi_bytes[0]&128))
            return (registers[1][address()]>>(7-((spi_bits-16)%8)))&1;
        return 0;
    }
    if(pin==29 && !pins[31] && !direction[29] && adc_bits>=16){
        unsigned a=((adc_bytes[0]&31)<<8)|adc_bytes[1];
        if(a==1 && !strcmp(fault,"adc_id"))return 0;
        return (adc[a]>>(7-((adc_bits-16)%8)))&1;
    }
    return pins[pin];
}
uint32_t hal_read(uint32_t offset){
    switch(offset){
    case 0:return !strcmp(fault,"identity")?0:0x41444441;
    case 0x20:return 1024;
    case 0x44:return 0x54583101;
    case 0x48:return 0x47504901;
    case 0x80:return 0x41574701;
    case 0x30:return !strcmp(fault,"rate")?125000000:50000000;
    case 12:return 16|((capture_started && !strcmp(fault,"adc_timeout"))?8:3);
    case 0x24:case 0x28:
        if(pins[32] || adc[8]!=0x80)return 0;
        return (uint32_t)(ticks*50);
    case 0x2c:return (uint32_t)(ticks*50);
    case 0x40:return 0x300;
    default:break;
    }
    if(offset>=0x1000 && offset<0x3000){
        if(!strcmp(fault,"adc_pattern"))return 0;
        return adc[13]==1?0x8000:adc[13]==2?0xffff:adc[13]==3?0:((offset/4)&1)?0x5555:0xaaaa;
    }
    return 0;
}
void hal_write(uint32_t offset,uint32_t value){
    pl_writes++;
    if(offset==8 && value==1)capture_started=1;
}
int main(int argc,char **argv){
    assert(argc==2);fault=argv[1];registers[1][3]=0x43;adc[1]=0x32;
    if(strcmp(fault,"clock_timeout"))registers[1][0x1f]=0x4b;
    uint32_t args[4]={20,20,0,0},out[2048];unsigned count;
    int rc=adda_command(CMD_INIT,args,out,&count);
    int expected=!strcmp(fault,"identity")||!strcmp(fault,"adc_id")?BJT_ID:
                 !strcmp(fault,"rate")||!strcmp(fault,"clock_timeout")?BJT_CLOCK:
                 !strcmp(fault,"gpio")?BJT_GPIO:
                 !strcmp(fault,"adc_timeout")?BJT_TIMEOUT:BJT_READBACK;
    assert(rc==expected);
    if(!strcmp(fault,"identity") || !strcmp(fault,"rate"))assert(!gpio_calls && !pl_writes);
    else if(strcmp(fault,"gpio")){
        assert(pins[32]==1 && pins[33]==1);
        assert(registers[0][3]==0x33);
        if(!strncmp(fault,"adc_",4) && strcmp(fault,"adc_id"))assert(adc[13]==0);
    }
    assert(adda_command(CMD_CAPTURE,args,out,&count)==BJT_NOT_READY);
    assert(!count);
    printf("C_DRIVER_FAULT_PASS %s status=%d gpio=%u writes=%u\n",fault,rc,gpio_calls,pl_writes);
    return 0;
}
