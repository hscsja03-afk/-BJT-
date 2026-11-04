/* JTAG-fed eMMC writer with per-transfer readback verification. */
#include "xparameters.h"
#include "xil_cache.h"
#include "xil_printf.h"
#include "xsdps.h"
#include "xsdps_core.h"
#include "xstatus.h"
#ifdef EMMC_NETWORK_WRITER
#include "ethernet.h"
#include <stddef.h>
#endif
#include <stdint.h>
#include <string.h>

#define EMMC_IMAGE_SECTORS 14948352U
#define EMMC_BLOCK_BYTES 512U
#define EMMC_MAX_CALL_SECTORS 4096U
#define EMMC_INPUT_ADDR 0x01000000U
#define EMMC_VERIFY_ADDR 0x03000000U
#define CONTROL_MAGIC 0x454d4d43U
#define EMMC_CHUNK_SECTORS 65536U
#define EMMC_CHUNK_BYTES (EMMC_CHUNK_SECTORS * EMMC_BLOCK_BYTES)
#define EMMC_TOTAL_CHUNKS ((EMMC_IMAGE_SECTORS + EMMC_CHUNK_SECTORS - 1U) / EMMC_CHUNK_SECTORS)
#ifdef EMMC_NETWORK_WRITER
#define EMMC_NET_HEADER_BYTES 20U
#define EMMC_NET_DATA_BYTES (1472U - EMMC_NET_HEADER_BYTES)
#define EMMC_NET_MAX_PACKETS ((EMMC_CHUNK_BYTES + EMMC_NET_DATA_BYTES - 1U) / EMMC_NET_DATA_BYTES)
#define EMMC_NET_BITMAP_BYTES ((EMMC_NET_MAX_PACKETS + 7U) / 8U)
#ifndef EMMC_HOST_IP0
#define EMMC_HOST_IP0 192
#define EMMC_HOST_IP1 168
#define EMMC_HOST_IP2 0
#define EMMC_HOST_IP3 3
#endif
#endif

enum {
    STATUS_INIT = 0U,
    STATUS_IDLE = 1U,
    STATUS_BUSY = 2U,
    STATUS_DONE = 3U,
    STATUS_ERROR = 4U
};

enum {
    OP_DRY_RUN = 1U,
    OP_WRITE_VERIFY = 2U
};

enum {
    ERROR_CONFIG = 1U,
    ERROR_CARD_INIT = 2U,
    ERROR_CARD_ID = 3U,
    ERROR_CAPACITY = 4U,
    ERROR_RANGE = 5U,
    ERROR_OPERATION = 6U,
    ERROR_SOURCE_CRC = 7U,
    ERROR_EMMC_WRITE = 8U,
    ERROR_EMMC_READ = 9U,
    ERROR_READBACK = 10U,
    ERROR_NETWORK_INIT = 11U
};

typedef struct {
    uint32_t magic;
    uint32_t ready;
    uint32_t command;
    uint32_t operation;
    uint32_t start_lba;
    uint32_t block_count;
    uint32_t sequence;
    uint32_t completed_sequence;
    uint32_t status;
    uint32_t expected_crc;
    uint32_t actual_crc;
    uint32_t card_sectors;
    uint32_t error;
    uint32_t blocked_extcsd_writes;
#ifdef EMMC_NETWORK_WRITER
    uint32_t network_ready;
    uint32_t network_errors;
    uint32_t network_received_packets;
#endif
} writer_control;

volatile writer_control emmc_writer_control = {
    .magic = CONTROL_MAGIC,
    .status = STATUS_INIT
};

static XSdPs card;
static uint8_t ext_csd[512] __attribute__((aligned(32)));
static uint8_t *const input_buffer = (uint8_t *)(uintptr_t)EMMC_INPUT_ADDR;
static uint8_t *const verify_buffer = (uint8_t *)(uintptr_t)EMMC_VERIFY_ADDR;

/* Keep card initialization in one-bit default mode and forbid permanent EXT_CSD changes. */
s32 __wrap_XSdPs_EmmcModeInit(XSdPs *instance) {
    s32 status = XSdPs_Get_Mmc_ExtCsd(instance, ext_csd);
    if (status != XST_SUCCESS) return status;
    instance->BusWidth = XSDPS_1_BIT_WIDTH;
    instance->Mode = XSDPS_DEFAULT_SPEED_MODE;
    instance->SectorCount = (uint32_t)ext_csd[212] |
        ((uint32_t)ext_csd[213] << 8) |
        ((uint32_t)ext_csd[214] << 16) |
        ((uint32_t)ext_csd[215] << 24);
    return XST_SUCCESS;
}

s32 __wrap_XSdPs_MmcModeInit(XSdPs *instance) {
    return __wrap_XSdPs_EmmcModeInit(instance);
}

s32 __wrap_XSdPs_Set_Mmc_ExtCsd(XSdPs *instance, u32 argument) {
    (void)instance;
    (void)argument;
    emmc_writer_control.blocked_extcsd_writes++;
    return XST_FAILURE;
}

static uint32_t crc32(const uint8_t *data, uint32_t length) {
    uint32_t crc = 0xffffffffU;
    for (uint32_t i = 0; i < length; i++) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; bit++) {
            crc = (crc >> 1) ^ ((0U - (crc & 1U)) & 0xedb88320U);
        }
    }
    return ~crc;
}

static void stop_with_error(uint32_t error) {
    emmc_writer_control.error = error;
    emmc_writer_control.status = STATUS_ERROR;
    emmc_writer_control.ready = 1U;
    xil_printf("EMMC_WRITER_ERROR code=%u\r\n", error);
    for (;;) __asm__ volatile("wfi");
}

static void initialize_card(void) {
    static const uint32_t expected_cid[4] = {
        0x4dbea069U, 0x39381114U, 0x35384133U, 0x00d60103U
    };
    XSdPs_Config *config = XSdPs_LookupConfig(XPAR_XSDPS_0_BASEADDR);
    if (config == NULL) stop_with_error(ERROR_CONFIG);
    if (XSdPs_CfgInitialize(&card, config, config->BaseAddress) != XST_SUCCESS ||
        XSdPs_CardInitialize(&card) != XST_SUCCESS) {
        stop_with_error(ERROR_CARD_INIT);
    }
    for (unsigned i = 0; i < 4; i++) {
        if (card.CardID[i] != expected_cid[i]) stop_with_error(ERROR_CARD_ID);
    }
    if (card.SectorCount < EMMC_IMAGE_SECTORS) stop_with_error(ERROR_CAPACITY);
    emmc_writer_control.card_sectors = card.SectorCount;
    emmc_writer_control.ready = 1U;
    emmc_writer_control.status = STATUS_IDLE;
    xil_printf("EMMC_WRITER_READY sectors=%u CID=%08x %08x %08x %08x\r\n",
        card.SectorCount, card.CardID[0], card.CardID[1], card.CardID[2], card.CardID[3]);
}

static uint32_t process_command(void) {
    uint32_t lba = emmc_writer_control.start_lba;
    uint32_t count = emmc_writer_control.block_count;
    uint32_t operation = emmc_writer_control.operation;
    uint32_t length;
    uint32_t input_crc;

    if (count == 0U || count > 65536U || count > (UINT32_MAX / EMMC_BLOCK_BYTES) ||
        lba > EMMC_IMAGE_SECTORS || count > (EMMC_IMAGE_SECTORS - lba)) {
        emmc_writer_control.error = ERROR_RANGE;
        return STATUS_ERROR;
    }
    if (operation != OP_DRY_RUN && operation != OP_WRITE_VERIFY) {
        emmc_writer_control.error = ERROR_OPERATION;
        return STATUS_ERROR;
    }

    length = count * EMMC_BLOCK_BYTES;
    input_crc = crc32(input_buffer, length);
    emmc_writer_control.actual_crc = input_crc;
    if (input_crc != emmc_writer_control.expected_crc) {
        emmc_writer_control.error = ERROR_SOURCE_CRC;
        return STATUS_ERROR;
    }
    if (operation == OP_DRY_RUN) return STATUS_DONE;

    for (uint32_t offset = 0; offset < count;) {
        uint32_t segment = count - offset;
        uint32_t bytes;
        const uint8_t *source;
        if (segment > EMMC_MAX_CALL_SECTORS) segment = EMMC_MAX_CALL_SECTORS;
        bytes = segment * EMMC_BLOCK_BYTES;
        source = input_buffer + offset * EMMC_BLOCK_BYTES;
        if (XSdPs_WritePolled(&card, lba + offset, segment, source) != XST_SUCCESS) {
            emmc_writer_control.error = ERROR_EMMC_WRITE;
            return STATUS_ERROR;
        }
        if (XSdPs_ReadPolled(&card, lba + offset, segment, verify_buffer) != XST_SUCCESS) {
            emmc_writer_control.error = ERROR_EMMC_READ;
            return STATUS_ERROR;
        }
        if (memcmp(source, verify_buffer, bytes) != 0) {
            emmc_writer_control.error = ERROR_READBACK;
            return STATUS_ERROR;
        }
        offset += segment;
    }
    return STATUS_DONE;
}

#ifdef EMMC_NETWORK_WRITER
enum {
    NET_OP_HELLO = 1U,
    NET_OP_BEGIN = 2U,
    NET_OP_DATA = 3U,
    NET_OP_COMMIT = 4U
};

static const uint8_t host_ip[4] = {EMMC_HOST_IP0, EMMC_HOST_IP1, EMMC_HOST_IP2, EMMC_HOST_IP3};
static uint8_t packet_bitmap[EMMC_NET_BITMAP_BYTES];
static uint32_t active_chunk;
static uint32_t active_lba;
static uint32_t active_sectors;
static uint32_t active_bytes;
static uint32_t active_packet_count;
static uint32_t received_packet_count;
static uint32_t expected_chunk;
static uint32_t last_chunk = UINT32_MAX;
static uint32_t last_chunk_crc;
static uint8_t chunk_active;

static uint16_t read_be16(const uint8_t *p) {
    return (uint16_t)(((uint16_t)p[0] << 8) | p[1]);
}

static uint32_t read_be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
        ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static uint32_t required_sectors(uint32_t lba) {
    uint32_t remaining = EMMC_IMAGE_SECTORS - lba;
    return remaining < EMMC_CHUNK_SECTORS ? remaining : EMMC_CHUNK_SECTORS;
}

static int network_receive(const uint8_t source_ip[4], const uint8_t *packet,
                           size_t packet_length) {
    uint32_t chunk;
    uint32_t arg0;
    uint32_t arg1;
    uint8_t operation;

    if (memcmp(source_ip, host_ip, sizeof(host_ip)) != 0 ||
        packet_length < EMMC_NET_HEADER_BYTES || memcmp(packet, "EMMC", 4) != 0 ||
        packet[5] != 1U || read_be16(packet + 6) != EMMC_NET_HEADER_BYTES) {
        return 0;
    }

    operation = packet[4];
    chunk = read_be32(packet + 8);
    arg0 = read_be32(packet + 12);
    arg1 = read_be32(packet + 16);

    if (operation == NET_OP_HELLO) {
        return packet_length == EMMC_NET_HEADER_BYTES && chunk == 0U &&
            emmc_writer_control.network_ready == 1U;
    }

    if (operation == NET_OP_BEGIN) {
        uint32_t sectors;
        if (packet_length != EMMC_NET_HEADER_BYTES || chunk >= EMMC_TOTAL_CHUNKS ||
            chunk != expected_chunk) {
            return 0;
        }
        active_lba = chunk * EMMC_CHUNK_SECTORS;
        sectors = required_sectors(active_lba);
        if (arg0 != active_lba || arg1 != sectors) return 0;
        if (chunk_active) {
            return chunk == active_chunk && active_lba == arg0 && active_sectors == arg1;
        }
        active_chunk = chunk;
        active_sectors = sectors;
        active_bytes = sectors * EMMC_BLOCK_BYTES;
        active_packet_count = (active_bytes + EMMC_NET_DATA_BYTES - 1U) / EMMC_NET_DATA_BYTES;
        received_packet_count = 0U;
        memset(packet_bitmap, 0, (active_packet_count + 7U) / 8U);
        chunk_active = 1U;
        xil_printf("EMMC_NET_CHUNK_BEGIN seq=%u lba=%u sectors=%u bytes=%u\r\n",
            chunk + 1U, active_lba, active_sectors, active_bytes);
        return 1;
    }

    if (operation == NET_OP_DATA) {
        uint32_t offset;
        uint32_t expected_bytes;
        uint32_t bitmap_index;
        uint8_t bitmap_mask;
        if (packet_length < EMMC_NET_HEADER_BYTES || !chunk_active || chunk != active_chunk ||
            arg0 >= active_packet_count || arg1 != packet_length - EMMC_NET_HEADER_BYTES) {
            return 0;
        }
        offset = arg0 * EMMC_NET_DATA_BYTES;
        expected_bytes = active_bytes - offset;
        if (expected_bytes > EMMC_NET_DATA_BYTES) expected_bytes = EMMC_NET_DATA_BYTES;
        if (arg1 != expected_bytes) return 0;
        bitmap_index = arg0 >> 3;
        bitmap_mask = (uint8_t)(1U << (arg0 & 7U));
        if (packet_bitmap[bitmap_index] & bitmap_mask) {
            return memcmp(input_buffer + offset, packet + EMMC_NET_HEADER_BYTES, expected_bytes) == 0;
        }
        memcpy(input_buffer + offset, packet + EMMC_NET_HEADER_BYTES, expected_bytes);
        packet_bitmap[bitmap_index] |= bitmap_mask;
        received_packet_count++;
        emmc_writer_control.network_received_packets++;
        return 1;
    }

    if (operation == NET_OP_COMMIT) {
        uint32_t input_crc;
        uint32_t result;
        if (packet_length != EMMC_NET_HEADER_BYTES) return 0;
        if (chunk == last_chunk && arg0 == last_chunk_crc) return 1;
        if (!chunk_active || chunk != active_chunk || arg1 != active_sectors ||
            received_packet_count != active_packet_count) {
            return 0;
        }
        input_crc = crc32(input_buffer, active_bytes);
        if (input_crc != arg0) {
            emmc_writer_control.network_errors++;
            xil_printf("EMMC_NET_CRC_ERROR seq=%u expected=%08x actual=%08x packets=%u/%u\r\n",
                chunk + 1U, arg0, input_crc, received_packet_count, active_packet_count);
            return 0;
        }

        emmc_writer_control.status = STATUS_BUSY;
        emmc_writer_control.sequence = chunk + 1U;
        emmc_writer_control.operation = OP_WRITE_VERIFY;
        emmc_writer_control.start_lba = active_lba;
        emmc_writer_control.block_count = active_sectors;
        emmc_writer_control.expected_crc = input_crc;
        result = process_command();
        emmc_writer_control.status = result;
        if (result != STATUS_DONE) {
            emmc_writer_control.network_errors++;
            xil_printf("EMMC_NET_WRITE_ERROR seq=%u status=%u error=%u\r\n",
                chunk + 1U, result, emmc_writer_control.error);
            return 0;
        }

        emmc_writer_control.completed_sequence = chunk + 1U;
        last_chunk = chunk;
        last_chunk_crc = input_crc;
        expected_chunk++;
        chunk_active = 0U;
        xil_printf("EMMC_NET_CHUNK_DONE seq=%u lba=%u sectors=%u crc32=%08x\r\n",
            chunk + 1U, active_lba, active_sectors, input_crc);
        return 1;
    }

    return 0;
}

int main(void) {
    Xil_DCacheDisable();
    Xil_ICacheDisable();
    initialize_card();
    ethernet_set_udp_handler(network_receive);
    if (ethernet_init() != 0) stop_with_error(ERROR_NETWORK_INIT);
    emmc_writer_control.network_ready = 1U;
    xil_printf("EMMC_NET_READY ip=192.168.0.2 port=5001 sectors=%u\r\n", EMMC_IMAGE_SECTORS);

    while (emmc_writer_control.completed_sequence < EMMC_TOTAL_CHUNKS &&
           emmc_writer_control.status != STATUS_ERROR) {
        ethernet_poll();
    }
    if (emmc_writer_control.status != STATUS_ERROR) {
        xil_printf("EMMC_IMAGE_WRITE_COMPLETE sectors=%u\r\n", EMMC_IMAGE_SECTORS);
    }
    for (;;) __asm__ volatile("wfi");
}
#else
int main(void) {
    uint32_t last_sequence = 0U;
    Xil_DCacheDisable();
    Xil_ICacheDisable();
    initialize_card();

    for (;;) {
        if (emmc_writer_control.command == 0U) {
            __asm__ volatile("wfi");
            continue;
        }
        uint32_t sequence = emmc_writer_control.sequence;
        emmc_writer_control.command = 0U;
        emmc_writer_control.status = STATUS_BUSY;
        if (sequence == 0U || sequence == last_sequence) {
            emmc_writer_control.error = ERROR_OPERATION;
            emmc_writer_control.completed_sequence = sequence;
            emmc_writer_control.status = STATUS_ERROR;
            continue;
        }
        uint32_t result = process_command();
        emmc_writer_control.completed_sequence = sequence;
        emmc_writer_control.status = result;
        last_sequence = sequence;
    }
}
#endif
