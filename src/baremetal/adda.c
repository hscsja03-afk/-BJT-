/* C port of the project's reviewed GPIO-SPI / PL register drivers.
 * No heap, DDR, filesystem or OS; all analog outputs start muted.
 */
#include "adda.h"
#define TRY(call) do { int rc_=(call); if(rc_) return rc_; } while(0)
enum { SCLK=7,MOSI,MISO,DAC_CS,DAC_RESET,IQSEL,CLOCK_CS,
       SDIO=29,ADC_SCLK,ADC_CS,DATA_OE,CTRL_OE };
static unsigned claimed,ready,tx_ready,released=3,sequence;
static uint32_t codes[3],rates[3],scratch[BJT_PAYLOAD_WORDS];

static int wait_reg(unsigned offset,uint32_t mask,uint32_t value,unsigned us) {
    uint64_t end=hal_us()+us;
    do { if((hal_read(offset)&mask)==value) return 0; } while(hal_us()<end);
    return BJT_TIMEOUT;
}
static void spi_begin(unsigned cs) {
    hal_pin(DAC_CS,1); hal_pin(CLOCK_CS,1); hal_pin(SCLK,0);
    hal_delay(1); hal_pin(cs,0); hal_delay(1);
}
static void spi_end(unsigned cs) {hal_delay(1);hal_pin(cs,1);hal_delay(1);}
static unsigned spi_byte(unsigned value) {
    unsigned out=0;
    for(int bit=7;bit>=0;bit--) {
        hal_pin(MOSI,(value>>bit)&1);hal_delay(1);hal_pin(SCLK,1);
        hal_delay(1);out=(out<<1)|hal_sense(MISO);hal_pin(SCLK,0);
    }
    return out;
}
static void spi_write(unsigned device,unsigned address,unsigned value) {
    unsigned cs=device==9516?CLOCK_CS:DAC_CS;
    spi_begin(cs);if(device==9516)spi_byte(address>>8);
    spi_byte(address&255);spi_byte(value);spi_end(cs);
}
static unsigned spi_read(unsigned device,unsigned address) {
    unsigned cs=device==9516?CLOCK_CS:DAC_CS,out=0;
    spi_begin(cs);
    if(device==9747) {spi_byte(0x80|address);out=spi_byte(0);}
    else {
        spi_byte(0x80|(address>>8));spi_byte(address&255);hal_pin(MOSI,0);
        for(unsigned i=0;i<8;i++) {
            hal_delay(1);out=(out<<1)|hal_sense(MISO);
            hal_pin(SCLK,1);hal_delay(1);hal_pin(SCLK,0);
        }
    }
    spi_end(cs);return out;
}
static unsigned adc_transfer(unsigned address,unsigned value,unsigned read) {
    unsigned command=address|(read?0x8000:0),out=0;
    hal_pin(ADC_SCLK,0);hal_pin(ADC_CS,1);hal_pin(SDIO,0);hal_output(SDIO,1);
    hal_delay(1);hal_pin(ADC_CS,0);hal_delay(1);
    unsigned bits=read?16:24;
    uint32_t tx=read?command:(command<<8)|value;
    for(int bit=(int)bits-1;bit>=0;bit--) {
        hal_pin(SDIO,(tx>>bit)&1);hal_delay(1);hal_pin(ADC_SCLK,1);hal_delay(1);
        if(read && bit==0)hal_output(SDIO,0);
        hal_pin(ADC_SCLK,0);hal_delay(1);
    }
    if(read)for(unsigned i=0;i<8;i++) {
        hal_delay(1);out=(out<<1)|hal_sense(SDIO);
        hal_pin(ADC_SCLK,1);hal_delay(1);hal_pin(ADC_SCLK,0);hal_delay(1);
    }
    hal_pin(ADC_CS,1);hal_delay(1);hal_pin(SDIO,0);hal_output(SDIO,1);
    return out;
}
static int mute(unsigned mask) {
    unsigned value=0x30|(3^mask);spi_write(9747,3,value);hal_delay(1000);
    return spi_read(9747,3)==value?0:BJT_READBACK;
}
static int dac_init(void) {
    static const unsigned settings[][2]={{0,0},{3,0x33},{2,0x80},{10,0},
        {11,0xf9},{12,1},{15,0xf9},{16,1}};
    hal_pin(DAC_RESET,1);hal_delay(10);hal_pin(DAC_RESET,0);hal_delay(100);
    for(unsigned i=0;i<8;i++)spi_write(9747,settings[i][0],settings[i][1]);
    for(unsigned i=0;i<8;i++)if(spi_read(9747,settings[i][0])!=settings[i][1])return BJT_READBACK;
    return 0;
}
static int clocks_init(void) {
    /* Baseline50 only: ADC /20 and DAC /20 from 1 GHz. */
    static const unsigned settings[][2]={{0x10,0x4c},{0x11,1},{0x12,0},{0x13,0},
        {0x14,5},{0x15,0},{0x16,4},{0x17,0xb4},{0x18,6},{0x19,0},{0x1a,0},
        {0x1b,0xa0},{0x1c,3},{0x1d,0},{0xf0,10},{0xf1,10},{0xf2,10},
        {0xf3,10},{0xf4,10},{0xf5,10},{0x140,0x43},{0x141,0x43},
        {0x142,0x43},{0x143,0x43},{0x199,0x99},{0x19a,0},{0x19b,0},
        {0x19c,0x20},{0x19d,0},{0x19e,0x99},{0x19f,0},{0x1a0,0},
        {0x1a1,0x20},{0x1a2,0},{0x1e0,0},{0x1e1,2},{0x230,0}};
    spi_write(9516,0,0x99);if(spi_read(9516,3)!=0x43)return BJT_ID;
    for(unsigned i=0;i<sizeof(settings)/sizeof(settings[0]);i++)
        spi_write(9516,settings[i][0],settings[i][1]);
    spi_write(9516,0x232,1);spi_write(9516,4,1);
    for(unsigned i=0;i<sizeof(settings)/sizeof(settings[0]);i++)
        if(spi_read(9516,settings[i][0])!=settings[i][1])return BJT_READBACK;
    spi_write(9516,0x18,7);spi_write(9516,0x232,1);
    uint64_t end=hal_us()+2000000;
    while((spi_read(9516,0x1f)&0x4b)!=0x4b) {
        if(hal_us()>=end)return BJT_CLOCK;
        hal_delay(1000);
    }
    spi_write(9516,0x140,0x42);spi_write(9516,0x142,0x42);spi_write(9516,0x232,1);
    spi_write(9516,0x230,1);spi_write(9516,0x232,1);hal_delay(10);
    spi_write(9516,0x230,0);spi_write(9516,0x232,1);hal_delay(1000);
    return spi_read(9516,0x140)==0x42 && spi_read(9516,0x142)==0x42?0:BJT_READBACK;
}
static int adc_init(void) {
    static const unsigned settings[][2]={{8,0x80},{9,1},{11,0},{13,0},
        {0x14,0},{0x16,0},{0x17,0},{0x18,0xc0}};
    adc_transfer(0,0x3c,0);hal_delay(1000);adc_transfer(0,0x18,0);
    if(adc_transfer(1,0,1)!=0x32)return BJT_ID;
    adc_transfer(5,3,0);
    for(unsigned i=0;i<8;i++)adc_transfer(settings[i][0],settings[i][1],0);
    adc_transfer(0xff,1,0);hal_delay(1000);
    int rc=0;
    for(unsigned ch=1;ch<=2;ch++) {
        adc_transfer(5,ch,0);
        for(unsigned i=0;i<8;i++)if(adc_transfer(settings[i][0],0,1)!=settings[i][1])rc=BJT_READBACK;
    }
    adc_transfer(5,3,0);return rc;
}
static int adc_mode(unsigned mode) {
    adc_transfer(5,3,0);adc_transfer(13,mode,0);adc_transfer(0xff,1,0);hal_delay(1000);
    int rc=0;
    for(unsigned ch=1;ch<=2;ch++) {
        adc_transfer(5,ch,0);if((adc_transfer(13,0,1)&7)!=mode)rc=BJT_READBACK;
    }
    adc_transfer(5,3,0);return rc;
}
static int capture(uint32_t *out) {
    if(hal_read(12)&8)return BJT_NOT_READY;
    hal_write(8,1);TRY(wait_reg(12,11,3,500000));
    for(unsigned i=0;i<1024;i++) {
        out[i]=hal_read(0x2000+4*i);out[1024+i]=hal_read(0x1000+4*i);
        if((out[i]|out[1024+i])&~0x1ffffU)return BJT_READBACK;
    }
    sequence++;return 0;
}
static int digital_test(void) {
    int rc=0;
    for(unsigned mode=1;mode<=4 && !rc;mode++) {
        rc=adc_mode(mode);if(rc)break;rc=capture(scratch);if(rc)break;
        unsigned expected=mode==1?0x8000:mode==2?0xffff:0;
        for(unsigned ch=0;ch<2;ch++)for(unsigned i=0;i<1024;i++) {
            unsigned v=scratch[ch*1024+i]&65535;
            if(mode!=4 ? v!=expected : ((v!=0xaaaa && v!=0x5555) ||
                (i && v==(scratch[ch*1024+i-1]&65535))))rc=BJT_READBACK;
        }
    }
    int restore=adc_mode(0);return rc?rc:restore;
}
static int awg_dc(unsigned ch,unsigned code) {
    TRY(wait_reg(0x84,1U<<ch,0,500000));
    if(!(hal_read(12)&16))return BJT_CLOCK;
    for(unsigned i=0;i<256;i++)hal_write(0x3000+ch*0x1000+4*i,code);
    hal_write(0x8c+4*ch,0);hal_write(0x94+4*ch,0);hal_write(0x88,1U<<ch);
    return wait_reg(0x84,1U<<ch,0,500000);
}
static void i2c_pins(unsigned v){released=v&3;hal_write(0x40,released);}
static unsigned i2c_lines(void){return (hal_read(0x40)>>8)&3;}
static int i2c_high(void){i2c_pins(released|1);for(unsigned i=0;i<100;i++){hal_delay(2);if(i2c_lines()&1)return 0;}return BJT_TIMEOUT;}
static void i2c_low(void){i2c_pins(released&~1U);hal_delay(2);}
static int i2c_start(void){i2c_pins(released|2);hal_delay(2);TRY(i2c_high());if(!(i2c_lines()&2))return BJT_BUS;i2c_pins(released&~2U);hal_delay(2);i2c_low();return 0;}
static int i2c_stop(void){i2c_pins(0);hal_delay(2);int rc=i2c_high();i2c_pins(3);hal_delay(2);return rc?rc:i2c_lines()==3?0:BJT_BUS;}
static int i2c_send(unsigned v){
    for(int bit=7;bit>=0;bit--){i2c_pins((released&1)|(((v>>bit)&1)<<1));hal_delay(2);TRY(i2c_high());i2c_low();}
    i2c_pins(released|2);hal_delay(2);TRY(i2c_high());int rc=(i2c_lines()&2)?BJT_BUS:0;i2c_low();return rc;
}
static int i2c_recv(unsigned ack,unsigned *value){
    unsigned v=0;i2c_pins(released|2);hal_delay(2);
    for(unsigned i=0;i<8;i++){TRY(i2c_high());v=(v<<1)|((i2c_lines()>>1)&1);i2c_low();}
    i2c_pins((released&1)|(ack?0:2));hal_delay(2);TRY(i2c_high());i2c_low();i2c_pins(released|2);*value=v;return 0;
}
static int tx_body(unsigned reg,unsigned *value,unsigned read){
    TRY(i2c_start());TRY(i2c_send(0x90));TRY(i2c_send(reg));
    if(read){unsigned hi,lo;TRY(i2c_start());TRY(i2c_send(0x91));TRY(i2c_recv(1,&hi));TRY(i2c_recv(0,&lo));*value=(hi<<8)|lo;}
    else {TRY(i2c_send(*value>>8));TRY(i2c_send(*value&255));}return 0;
}
static int tx_transfer(unsigned reg,unsigned *value,unsigned read){int rc=tx_body(reg,value,read),stop=i2c_stop();return rc?rc:stop;}
static int tx_verified(unsigned reg,unsigned value,unsigned mask){
    unsigned got;TRY(tx_transfer(reg,&got,1));got=(got&~mask)|(value&mask);
    TRY(tx_transfer(reg,&got,0));TRY(tx_transfer(reg,&got,1));return (got&mask)==(value&mask)?0:BJT_READBACK;
}
static int tx_init(void){
    unsigned id;i2c_pins(3);hal_delay(2);if(i2c_lines()!=3)return BJT_BUS;
    TRY(tx_transfer(1,&id,1));if(id!=0x2195)return BJT_ID;
    TRY(tx_verified(3,1,0x101));TRY(tx_verified(4,0x101,0x101));
    TRY(tx_verified(2,0,1));TRY(tx_verified(8,0,0xfff0));
    TRY(tx_transfer(7,&id,1));if(id&1)return BJT_BUS;tx_ready=1;return 0;
}
int adda_stop(void){
    int rc=0,other=0;ready=0;
    if(claimed){rc=mute(0);other=tx_verified(3,1,0x101);hal_pin(DATA_OE,1);hal_pin(CTRL_OE,1);}
    tx_ready=0;return rc?rc:other;
}
static int initialize(void){
    static const unsigned offsets[]={0,0x20,0x44,0x48,0x80};
    static const uint32_t ids[]={0x41444441,1024,0x54583101,0x47504901,0x41574701};
    if(ready)return BJT_NOT_READY;
    for(unsigned i=0;i<5;i++)if(hal_read(offsets[i])!=ids[i])return BJT_ID;
    if(hal_read(0x30)!=50000000)return BJT_CLOCK;
    TRY(hal_gpio_init());claimed=1;hal_write(4,6);hal_delay(1000);hal_write(4,7);
    TRY(dac_init());TRY(clocks_init());hal_write(4,3);TRY(wait_reg(12,16,16,1000000));
    /* ADC DCO reaches the FPGA through the enabled data path. Configure the
     * converter and translator before treating its clock counter as valid. */
    hal_pin(CTRL_OE,0);TRY(adc_init());hal_pin(DATA_OE,0);hal_delay(1000);
    uint32_t before[3];for(unsigned i=0;i<3;i++)before[i]=hal_read(0x24+4*i);
    uint64_t start=hal_us();hal_delay(100000);uint64_t elapsed=hal_us()-start;
    for(unsigned i=0;i<3;i++){
        rates[i]=(uint32_t)((uint64_t)(hal_read(0x24+4*i)-before[i])*1000000/elapsed);
        if(rates[i]<49000000 || rates[i]>51000000)return BJT_CLOCK;
    }
    TRY(digital_test());
    TRY(tx_init());codes[0]=0;
    for(unsigned ch=0;ch<2;ch++){TRY(awg_dc(ch,32768));codes[ch+1]=32768;}
    TRY(mute(0));ready=1;return 0;
}
static int output(unsigned ch,uint32_t *out){
    unsigned reg;if(ch>2)return BJT_ARGUMENT;
    if(ch==0){if(!tx_ready)return BJT_NOT_READY;TRY(tx_transfer(7,&reg,1));if(reg&1)return BJT_BUS;
        TRY(tx_transfer(8,&reg,1));out[0]=reg>>4;TRY(tx_transfer(3,&reg,1));out[1]=!(reg&1);}
    else {reg=spi_read(9747,3);if((reg&0x30)!=0x30)return BJT_READBACK;out[0]=codes[ch];out[1]=!(reg&(1U<<(ch-1)));}
    return 0;
}
int adda_command(unsigned op,const uint32_t a[4],uint32_t *out,unsigned *count){
    *count=0;
    if(op==CMD_INIT){if(a[0]!=20 || a[1]!=20)return BJT_ARGUMENT;int rc=initialize();
        if(rc){int stop=adda_stop();out[0]=(uint32_t)stop;*count=1;return rc;}
        out[0]=rates[1];out[1]=rates[0];out[2]=rates[2];*count=3;return 0;}
    if(op==CMD_STOP)return adda_stop();
    if(!ready)return BJT_NOT_READY;
    if(op==CMD_CAPTURE){if(!(hal_read(12)&16))return BJT_CLOCK;TRY(capture(out));*count=2048;return 0;}
    if(op==CMD_SET){if(a[0]>2 || a[1]>(a[0]?65535U:4095U))return BJT_ARGUMENT;
        if(a[0]){TRY(awg_dc(a[0]-1,a[1]));}else {TRY(tx_verified(8,a[1]<<4,0xfff0));}
        codes[a[0]]=a[1];TRY(output(a[0],out));*count=2;return 0;}
    if(op==CMD_ENABLE){if(a[0]>2 || a[1]>1)return BJT_ARGUMENT;
        if(a[0]){unsigned mask=3^(spi_read(9747,3)&3),bit=1U<<(a[0]-1);TRY(mute(a[1]?mask|bit:mask&~bit));}
        else {TRY(tx_verified(3,a[1]?0:1,0x101));}TRY(output(a[0],out));*count=2;return 0;}
    if(op==CMD_OUTPUT){TRY(output(a[0],out));*count=2;return 0;}
    if(op==CMD_GPIO){if(a[0]>127 || a[1]>127)return BJT_ARGUMENT;
        unsigned before=hal_read(0x4c);if(a[0]){hal_write(0x50,(a[0]<<8)|a[1]);TRY(wait_reg(0x4c,a[0],a[0]&a[1],500000));}
        unsigned now=hal_read(0x4c);if((((now^before)&~a[0])&127) || (((now^(now>>8))&a[0])&127))return BJT_GPIO;
        out[0]=now&127;out[1]=(now>>8)&127;out[2]=hal_read(0x54);*count=3;return 0;}
    return BJT_ARGUMENT;
}
