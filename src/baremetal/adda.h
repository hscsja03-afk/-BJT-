#ifndef ADDA_BAREMETAL_H
#define ADDA_BAREMETAL_H
#include <stdint.h>

enum { BJT_OK, BJT_ARGUMENT, BJT_TIMEOUT, BJT_ID, BJT_NOT_READY,
       BJT_READBACK, BJT_GPIO, BJT_DISABLED, BJT_CLOCK, BJT_BUS };
enum { CMD_PING=1, CMD_INIT, CMD_CAPTURE, CMD_SET, CMD_ENABLE,
       CMD_OUTPUT, CMD_GPIO, CMD_STOP, CMD_OCM_TEST };
#define BJT_PAYLOAD_WORDS 2048U
uint32_t hal_read(uint32_t offset);
void hal_write(uint32_t offset,uint32_t value);
uint64_t hal_us(void);
void hal_delay(unsigned us);
int hal_gpio_init(void);
void hal_pin(unsigned pin,unsigned value);
unsigned hal_sense(unsigned pin);
void hal_output(unsigned pin,unsigned enabled);
int adda_command(unsigned op,const uint32_t args[4],uint32_t *out,unsigned *count);
int adda_stop(void);
#endif
