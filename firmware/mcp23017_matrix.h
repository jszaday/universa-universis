// Pure, host-testable matrix scan logic for MCP23017-based breakaway pieces.
// No QMK or hardware headers: the I2C bus is injected (see mx_bus_t).
//
// Row drive: MCP23017 outputs are push-pull. The active row is driven low and every
// other row is driven HIGH (not switched to input). That is safe with COL2ROW
// diodes: the diode cathode is on the row and the anode on the column, so a row at
// VDD reverse-biases it and a column (weak pull-up to VDD) cannot be pulled low
// by an unselected row. (A floating row would be equally safe; driving high keeps
// rows from picking up noise.)
//
// Wiring model (locked design): each chip drives a purely local COL2ROW diode
// matrix. Row pins are outputs, driven low one at a time; column pins are inputs
// with the chip's internal pull-ups; a pressed key reads 0 on its column pin.
// A chip may be absent: its keys read as released and the scan never blocks.
//
// Pin numbering used throughout: 0..7 = GPA0..GPA7, 8..15 = GPB0..GPB7.
// GPA7 (7) and GPB7 (15) are output-only on the MCP23017 (datasheet rev D, features
// list): they may be rows but never columns (mx_validate enforces this).
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define MX_MAX_CHIPS 8   // 3 address pins -> addresses 0x20..0x27
#define MX_MAX_PINS 16
#define MX_MAX_ROWS 32   // logical rows (bounded by the fixed state arrays)
#define MX_POS_NONE 0xFF // map entry with no key (unpopulated switch position)
#define MX_RETRY_PERIOD 256 // scans between init retries of a down chip (uint8_t wrap)

// MCP23017 registers, IOCON.BANK=0 (power-on default). Each address confirmed in
// MCP23017 datasheet DS20001952D Table 3-5; OLAT (0x14/0x15) is where GPIO writes
// land. The MCP23018 (QMK drivers/gpio/mcp23018.c) uses the same addresses.
enum {
    MX_REG_IODIRA = 0x00,
    MX_REG_IODIRB = 0x01,
    MX_REG_GPPUA  = 0x0C,
    MX_REG_GPPUB  = 0x0D,
    MX_REG_GPIOA  = 0x12, // reads port; writes go to OLAT
};

typedef uint32_t mx_row_t; // one logical row, bit n = column n (<= 32 columns)

typedef struct {
    uint8_t row, col;
} mx_pos_t; // logical QMK matrix position; row == MX_POS_NONE means no key

typedef struct {
    uint8_t addr;             // 7-bit I2C address (0x20 | A2A1A0)
    uint8_t n_rows, n_cols;   // each <= MX_MAX_PINS
    uint8_t row_pins[MX_MAX_PINS];
    uint8_t col_pins[MX_MAX_PINS];
    const mx_pos_t *map;      // n_rows * n_cols entries, row-major [row][col]
} mx_chip_cfg_t;

// Bus operations. addr is the 7-bit address; the glue shifts it. `len` bytes are
// transferred starting at `reg` with the chip's sequential (auto-increment) mode,
// so len == 2 at GPIOA/GPPUA/IODIRA covers port A then port B. Return false on
// NACK/timeout.
typedef struct {
    bool (*write)(void *ctx, uint8_t addr, uint8_t reg, const uint8_t *data, uint8_t len);
    bool (*read)(void *ctx, uint8_t addr, uint8_t reg, uint8_t *data, uint8_t len);
    void *ctx;
} mx_bus_t;

typedef struct {
    mx_bus_t bus;
    const mx_chip_cfg_t *chips;
    uint8_t n_chips;
    uint8_t n_rows, n_cols; // logical matrix size
    uint8_t up[MX_MAX_CHIPS];    // 1 when the chip is initialised and answering
    uint8_t retry[MX_MAX_CHIPS]; // scans since the chip went down (wraps at 256)
    mx_row_t last[MX_MAX_ROWS];
} mx_state_t;

// Returns NULL if the config is usable, else a message naming the cause and the
// fix. Checks pins, address range/uniqueness, and map bounds.
const char *mx_validate(const mx_chip_cfg_t *chips, uint8_t n_chips, uint8_t n_rows, uint8_t n_cols);

// Binds config and bus, then tries to initialise every chip once. A chip that
// does not answer is left down (retried by mx_scan). Does not validate: call
// mx_validate first.
void mx_init(mx_state_t *s, const mx_bus_t *bus, const mx_chip_cfg_t *chips, uint8_t n_chips, uint8_t n_rows, uint8_t n_cols);

// Raw (undebounced) scan into out[0..n_rows). Down chips contribute no keys and
// cost no bus traffic except one init attempt every MX_RETRY_PERIOD scans.
// Returns true if out differs from the previous scan.
bool mx_scan(mx_state_t *s, mx_row_t *out);

// Number of chips currently up (for diagnostics).
uint8_t mx_chips_up(const mx_state_t *s);
