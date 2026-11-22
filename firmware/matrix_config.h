// rev1 matrix layout, table-driven: one entry per MCP23017 chip.
//
// Source: the CSV blocks in section 8 of docs/rev1-spec.md (chips U1 0x20, U3 0x22,
// U4 0x23, U5 0x24, U6 0x25; U2 is retired and 0x21 unused). test_matrix.c parses
// those blocks and fails if any entry here differs, so after a spec change update
// this file (and nothing else) until `make test` passes.
//
// Pin numbers: 0..7 = GPA0..GPA7, 8..15 = GPB0..GPB7. Address = 0x20 | A2A1A0.
// Rows are scanned as in the spec's section 7: the active row is an output driven
// low, every other row is high impedance (never driven high).
//
// Logical QMK matrix rule: logical row = rev0 row (R0..R5 -> 0..5), logical column =
// rev0 column (C0..C20 -> 0..20), so the matrix is 6 x 21 and a rev0 keymap carries
// over unchanged. The spec's rev0_row/rev0_col columns define it; the electrical
// (chip, row pin, column pin) is independent of it. Every position has a unique
// (rev0 row, rev0 col), checked by mx_validate. Cells with no switch are MX_NONE.
//
// U6 indicator outputs (Num, Caps, Scroll = GPB7, GPA2, GPA1) are not matrix lines:
// the scanner sets them as outputs driven high (LED off, spec D9) and never changes
// them. TODO(rev1-led): lock-state writes are not implemented; they must write only
// the indicator OLAT bits (OLATB 0x15 bit 7, OLATA 0x14 bits 1 and 2) so the row OLAT
// bits (held at 0) stay untouched.
//
// Register facts, confirmed in the MCP23017 datasheet DS20001952D (Table 3-5, BANK=0):
// IODIRA 0x00, IODIRB 0x01, GPPUA 0x0C, GPPUB 0x0D, GPIOA 0x12, GPIOB 0x13, OLATA
// 0x14, OLATB 0x15; IOCON (0x0A) resets to 0x00, so BANK=0 and SEQOP=0 (sequential)
// are the power-on state and the code never writes IOCON. QMK's
// drivers/gpio/mcp23018.c shows the same addresses, the 7-bit address shifted left
// by one for i2c_master, and a 100 ms timeout (QMK facts, not datasheet).
// GPA7 and GPB7 are output-only on the MCP23017: never use them as columns.
#pragma once
#include "mcp23017_matrix.h"

#define MX_LOGICAL_ROWS 6
#define MX_LOGICAL_COLS 21
#define MX_NUM_CHIPS 5

#define MX_P(r, c) {(r), (c)}
#define MX_NONE {MX_POS_NONE, MX_POS_NONE}

// U1 F-row (0x20): 1 rows x 13 columns
static const mx_pos_t mx_map_u1[1 * 13] = {
    MX_P(0, 0), MX_P(0, 2), MX_P(0, 3), MX_P(0, 4), MX_P(0, 5), MX_P(0, 6), MX_P(0, 7), MX_P(0, 8), MX_P(0, 9), MX_P(0, 10), MX_P(0, 11), MX_P(0, 12), MX_P(0, 13),
};

// U3 Main-L (0x22): 5 rows x 7 columns
static const mx_pos_t mx_map_u3[5 * 7] = {
    MX_P(1, 0), MX_P(1, 1), MX_P(1, 2), MX_P(1, 3), MX_P(1, 4), MX_P(1, 5), MX_P(1, 6),
    MX_P(2, 0), MX_P(2, 1), MX_P(2, 2), MX_P(2, 3), MX_P(2, 4), MX_P(2, 5), MX_P(2, 6),
    MX_P(3, 0), MX_P(3, 1), MX_P(3, 2), MX_P(3, 3), MX_P(3, 4), MX_P(3, 5), MX_P(3, 6),
    MX_P(4, 0), MX_P(4, 1), MX_P(4, 2), MX_P(4, 3), MX_P(4, 4), MX_P(4, 5), MX_P(4, 6),
    MX_P(5, 0), MX_P(5, 1), MX_P(5, 2), MX_P(5, 3), MX_P(5, 4), MX_P(5, 5), MX_P(5, 6),
};

// U4 Main-R (0x23): 5 rows x 7 columns
static const mx_pos_t mx_map_u4[5 * 7] = {
    MX_P(1, 7), MX_P(1, 8), MX_P(1, 9), MX_P(1, 10), MX_P(1, 11), MX_P(1, 12), MX_P(1, 13),
    MX_P(2, 7), MX_P(2, 8), MX_P(2, 9), MX_P(2, 10), MX_P(2, 11), MX_P(2, 12), MX_P(2, 13),
    MX_P(3, 7), MX_P(3, 8), MX_P(3, 9), MX_P(3, 10), MX_P(3, 11), MX_P(3, 12), MX_P(3, 13),
    MX_P(4, 7), MX_P(4, 8), MX_P(4, 9), MX_P(4, 10), MX_P(4, 11), MX_P(4, 12), MX_P(4, 13),
    MX_P(5, 7), MX_P(5, 8), MX_P(5, 9), MX_P(5, 10), MX_NONE, MX_NONE, MX_NONE,
};

// U5 Nav and F-nav (0x24): 5 rows x 3 columns
static const mx_pos_t mx_map_u5[5 * 3] = {
    MX_P(1, 14), MX_P(1, 15), MX_P(1, 16),
    MX_P(2, 14), MX_P(2, 15), MX_P(2, 16),
    MX_NONE, MX_P(4, 15), MX_NONE,
    MX_P(5, 14), MX_P(5, 15), MX_P(5, 16),
    MX_P(0, 14), MX_P(0, 15), MX_P(0, 16),
};

// U6 Numpad (0x25): 5 rows x 4 columns
static const mx_pos_t mx_map_u6[5 * 4] = {
    MX_P(1, 17), MX_P(1, 18), MX_P(1, 19), MX_P(1, 20),
    MX_P(2, 17), MX_P(2, 18), MX_P(2, 19), MX_P(2, 20),
    MX_P(3, 17), MX_P(3, 18), MX_P(3, 19), MX_P(3, 20),
    MX_P(4, 17), MX_P(4, 18), MX_P(4, 19), MX_P(4, 20),
    MX_P(5, 17), MX_NONE, MX_P(5, 19), MX_NONE,
};

static const mx_chip_cfg_t mx_chips[MX_NUM_CHIPS] = {
    {.addr = 0x20, .n_rows = 1, .n_cols = 13, .row_pins = {14}, .col_pins = {0, 1, 2, 3, 4, 5, 6, 13, 12, 11, 10, 9, 8}, .map = mx_map_u1},
    {.addr = 0x22, .n_rows = 5, .n_cols = 7, .row_pins = {2, 4, 7, 8, 10}, .col_pins = {0, 3, 5, 6, 9, 12, 11}, .map = mx_map_u3},
    {.addr = 0x23, .n_rows = 5, .n_cols = 7, .row_pins = {13, 12, 4, 6, 7}, .col_pins = {14, 0, 2, 3, 1, 5, 11}, .map = mx_map_u4},
    {.addr = 0x24, .n_rows = 5, .n_cols = 3, .row_pins = {0, 2, 7, 8, 15}, .col_pins = {14, 13, 1}, .map = mx_map_u5},
    {.addr = 0x25, .n_rows = 5, .n_cols = 4, .row_pins = {3, 14, 11, 9, 8}, .col_pins = {10, 12, 13, 0}, .ind_pins = {15, 2, 1}, .n_ind = 3, .map = mx_map_u6},
};
