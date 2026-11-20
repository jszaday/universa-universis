// rev1 matrix layout, table-driven: one entry per MCP23018 chip.
//
// *** PLACEHOLDER *** two invented chips so the scanner and tests have something
// to run. The real per-piece table (addresses, row/column pins, mapping to the
// logical QMK matrix) comes from docs/rev1-spec.md later and replaces the data
// below; nothing else in this directory should need to change.
//
// Pin numbers: 0..7 = GPA0..GPA7, 8..15 = GPB0..GPB7. Address = 0x20 | A2A1A0.
// map[] is row-major [chip row][chip column] -> logical {row, col}; use
// MX_NONE for a position with no switch.
//
// Register facts (verified) come from QMK drivers/gpio/mcp23018.c: IODIRA 0x00,
// IODIRB 0x01, GPPUA 0x0C, GPPUB 0x0D, GPIOA 0x12, GPIOB 0x13, 7-bit address
// shifted left by one for i2c_master, 100 ms timeout. Not verified against the
// datasheet: IOCON.BANK=0 being the power-on default (assumed; the code never
// writes IOCON).
#pragma once
#include "mcp23018_matrix.h"

#define MX_LOGICAL_ROWS 4
#define MX_LOGICAL_COLS 10
#define MX_NUM_CHIPS 2

#define MX_P(r, c) {(r), (c)}
#define MX_NONE {MX_POS_NONE, MX_POS_NONE}

// Chip 0 (0x20): rows GPA0-3, columns GPB0-4 -> logical cols 0-4, same order.
static const mx_pos_t mx_map_chip0[4 * 5] = {
    MX_P(0, 0), MX_P(0, 1), MX_P(0, 2), MX_P(0, 3), MX_P(0, 4),
    MX_P(1, 0), MX_P(1, 1), MX_P(1, 2), MX_P(1, 3), MX_P(1, 4),
    MX_P(2, 0), MX_P(2, 1), MX_P(2, 2), MX_P(2, 3), MX_P(2, 4),
    MX_P(3, 0), MX_P(3, 1), MX_P(3, 2), MX_P(3, 3), MX_NONE,
};

// Chip 1 (0x21): rows GPA0-3, columns GPB0-4 -> logical cols 9..5 (reversed,
// as on a mirrored half).
static const mx_pos_t mx_map_chip1[4 * 5] = {
    MX_P(0, 9), MX_P(0, 8), MX_P(0, 7), MX_P(0, 6), MX_P(0, 5),
    MX_P(1, 9), MX_P(1, 8), MX_P(1, 7), MX_P(1, 6), MX_P(1, 5),
    MX_P(2, 9), MX_P(2, 8), MX_P(2, 7), MX_P(2, 6), MX_P(2, 5),
    MX_P(3, 9), MX_P(3, 8), MX_P(3, 7), MX_P(3, 6), MX_P(3, 5),
};

static const mx_chip_cfg_t mx_chips[MX_NUM_CHIPS] = {
    {.addr = 0x20, .n_rows = 4, .n_cols = 5, .row_pins = {0, 1, 2, 3}, .col_pins = {8, 9, 10, 11, 12}, .map = mx_map_chip0},
    {.addr = 0x21, .n_rows = 4, .n_cols = 5, .row_pins = {0, 1, 2, 3}, .col_pins = {8, 9, 10, 11, 12}, .map = mx_map_chip1},
};
