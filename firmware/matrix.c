// QMK custom-matrix glue (CUSTOM_MATRIX = lite): binds mcp23017_matrix.c to
// QMK's i2c_master. Not compiled in this repo (no QMK tree available when it
// was written); it follows https://docs.qmk.fm/custom_matrix and the i2c_master
// API as used by QMK drivers/gpio/mcp23018.c. Expect to fix small build errors.
//
// Keyboard integration (not shipped here):
//   rules.mk:  CUSTOM_MATRIX = lite
//              SRC += matrix.c mcp23017_matrix.c
//              QUANTUM_LIB_SRC += i2c_master.c
//   config.h:  #define MATRIX_ROWS 4 / MATRIX_COLS 10  (= MX_LOGICAL_ROWS/COLS)
//              #define F_SCL 400000UL  (AVR; ARM/ChibiOS sets the bus speed in
//              its I2C driver config instead, e.g. I2C1_OPMODE / timing values)
//   The 400 kHz request is also made below, but F_SCL must be visible to
//   i2c_master.c, so the config.h define is the one that counts on AVR.
#include "matrix.h"
#include "i2c_master.h"
#include "debug.h"
#include "wait.h"
#include "matrix_config.h"

#ifndef F_SCL
#    define F_SCL 400000UL
#endif
#define MX_I2C_TIMEOUT_MS 100 // as QMK drivers/gpio/mcp23018.c

static bool bus_write(void *ctx, uint8_t addr, uint8_t reg, const uint8_t *d, uint8_t len) {
    (void)ctx;
    return i2c_write_register((uint8_t)(addr << 1), reg, d, len, MX_I2C_TIMEOUT_MS) == I2C_STATUS_SUCCESS;
}

static bool bus_read(void *ctx, uint8_t addr, uint8_t reg, uint8_t *d, uint8_t len) {
    (void)ctx;
    return i2c_read_register((uint8_t)(addr << 1), reg, d, len, MX_I2C_TIMEOUT_MS) == I2C_STATUS_SUCCESS;
}

static mx_state_t mx;
static bool       mx_ok;

void matrix_init_custom(void) {
    const char *err = mx_validate(mx_chips, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS);
    if (err) {
        dprintf("matrix config invalid: %s\n", err);
        mx_ok = false;
        return;
    }
    mx_ok = true;
    i2c_init();
    wait_ms(100); // let the extenders power up; QMK's driver waits 1000 ms once
    const mx_bus_t bus = {bus_write, bus_read, 0};
    mx_init(&mx, &bus, mx_chips, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS);
    dprintf("mcp23017: %u of %u chips up\n", mx_chips_up(&mx), MX_NUM_CHIPS);
}

bool matrix_scan_custom(matrix_row_t current_matrix[]) {
    if (!mx_ok) return false;
    mx_row_t raw[MX_LOGICAL_ROWS];
    bool     changed = mx_scan(&mx, raw);
    for (uint8_t r = 0; r < MX_LOGICAL_ROWS; r++) current_matrix[r] = (matrix_row_t)raw[r];
    return changed;
}
