#include "mcp23018_matrix.h"

#include <string.h>

static uint16_t pin_mask(const uint8_t *pins, uint8_t n) {
    uint16_t m = 0;
    for (uint8_t i = 0; i < n; i++) m |= (uint16_t)1 << pins[i];
    return m;
}

const char *mx_validate(const mx_chip_cfg_t *chips, uint8_t n_chips, uint8_t n_rows, uint8_t n_cols) {
    if (n_chips == 0 || n_chips > MX_MAX_CHIPS) return "chip count must be 1..8 (MCP23018 has 3 address pins): fix MX_NUM_CHIPS in matrix_config.h";
    if (n_rows == 0 || n_rows > MX_MAX_ROWS || n_cols == 0 || n_cols > 32) return "logical matrix must be 1..32 rows by 1..32 columns: fix MX_LOGICAL_ROWS/COLS in matrix_config.h";
    for (uint8_t i = 0; i < n_chips; i++) {
        const mx_chip_cfg_t *c = &chips[i];
        if (c->addr < 0x20 || c->addr > 0x27) return "chip address outside 0x20..0x27: use 0x20 | A2A1A0 for the chip's address pins";
        for (uint8_t j = 0; j < i; j++)
            if (chips[j].addr == c->addr) return "two chips share an I2C address: give each chip distinct A2A1A0 straps";
        if (c->n_rows == 0 || c->n_cols == 0 || c->n_rows > MX_MAX_PINS || c->n_cols > MX_MAX_PINS) return "chip row/column count must be 1..16: fix its n_rows/n_cols";
        for (uint8_t k = 0; k < c->n_rows; k++)
            if (c->row_pins[k] >= MX_MAX_PINS) return "row pin number > 15 (0-7 = GPA, 8-15 = GPB): fix row_pins";
        for (uint8_t k = 0; k < c->n_cols; k++)
            if (c->col_pins[k] >= MX_MAX_PINS) return "column pin number > 15 (0-7 = GPA, 8-15 = GPB): fix col_pins";
        uint16_t rm = pin_mask(c->row_pins, c->n_rows), cm = pin_mask(c->col_pins, c->n_cols);
        if (__builtin_popcount(rm) != c->n_rows || __builtin_popcount(cm) != c->n_cols) return "a pin is listed twice in a chip's rows or columns: make each pin appear once";
        if (rm & cm) return "a pin is both a row and a column: assign it to one role";
        if (!c->map) return "chip has no map: provide n_rows * n_cols mx_pos_t entries";
        for (uint16_t k = 0; k < (uint16_t)c->n_rows * c->n_cols; k++) {
            if (c->map[k].row == MX_POS_NONE) continue;
            if (c->map[k].row >= n_rows || c->map[k].col >= n_cols) return "map entry outside the logical matrix: fix the map or the logical size";
        }
    }
    return 0;
}

// Write the three configuration registers. GPIO first so rows come up high
// (no spurious low pulse) before IODIR turns them into outputs.
static bool chip_init(const mx_bus_t *bus, const mx_chip_cfg_t *c) {
    uint16_t rows = pin_mask(c->row_pins, c->n_rows);
    uint16_t cols = pin_mask(c->col_pins, c->n_cols);
    uint8_t high[2]   = {0xFF, 0xFF};
    uint8_t pullup[2] = {(uint8_t)(cols & 0xFF), (uint8_t)(cols >> 8)};
    uint16_t dir      = (uint16_t)~rows; // 1 = input; only rows are outputs
    uint8_t iodir[2]  = {(uint8_t)(dir & 0xFF), (uint8_t)(dir >> 8)};
    return bus->write(bus->ctx, c->addr, MX_REG_GPIOA, high, 2) && bus->write(bus->ctx, c->addr, MX_REG_GPPUA, pullup, 2) && bus->write(bus->ctx, c->addr, MX_REG_IODIRA, iodir, 2);
}

void mx_init(mx_state_t *s, const mx_bus_t *bus, const mx_chip_cfg_t *chips, uint8_t n_chips, uint8_t n_rows, uint8_t n_cols) {
    memset(s, 0, sizeof *s);
    s->bus = *bus;
    s->chips = chips;
    s->n_chips = n_chips;
    s->n_rows = n_rows;
    s->n_cols = n_cols;
    for (uint8_t i = 0; i < n_chips; i++) s->up[i] = chip_init(&s->bus, &chips[i]);
}

// Scan one chip into acc[]; false if the bus failed (acc is then to be discarded).
static bool scan_chip(const mx_bus_t *bus, const mx_chip_cfg_t *c, mx_row_t *acc) {
    for (uint8_t r = 0; r < c->n_rows; r++) {
        uint16_t drive = (uint16_t)~((uint16_t)1 << c->row_pins[r]);
        uint8_t out[2] = {(uint8_t)(drive & 0xFF), (uint8_t)(drive >> 8)};
        uint8_t in[2];
        if (!bus->write(bus->ctx, c->addr, MX_REG_GPIOA, out, 2)) return false;
        if (!bus->read(bus->ctx, c->addr, MX_REG_GPIOA, in, 2)) return false;
        uint16_t v = (uint16_t)in[0] | ((uint16_t)in[1] << 8);
        for (uint8_t k = 0; k < c->n_cols; k++) {
            if (v & ((uint16_t)1 << c->col_pins[k])) continue; // pulled up: released
            mx_pos_t p = c->map[r * c->n_cols + k];
            if (p.row != MX_POS_NONE) acc[p.row] |= (mx_row_t)1 << p.col;
        }
    }
    return true;
}

bool mx_scan(mx_state_t *s, mx_row_t *out) {
    memset(out, 0, sizeof(mx_row_t) * s->n_rows);
    for (uint8_t i = 0; i < s->n_chips; i++) {
        if (!s->up[i]) {
            if (++s->retry[i] == 0) s->up[i] = chip_init(&s->bus, &s->chips[i]); // keys stay released until the next scan
            continue;
        }
        mx_row_t acc[MX_MAX_ROWS];
        memset(acc, 0, sizeof(mx_row_t) * s->n_rows);
        if (scan_chip(&s->bus, &s->chips[i], acc)) {
            for (uint8_t r = 0; r < s->n_rows; r++) out[r] |= acc[r];
        } else {
            s->up[i] = 0; // went away mid-run: report released, retry later
            s->retry[i] = 0;
        }
    }
    bool changed = memcmp(out, s->last, sizeof(mx_row_t) * s->n_rows) != 0;
    memcpy(s->last, out, sizeof(mx_row_t) * s->n_rows);
    return changed;
}

uint8_t mx_chips_up(const mx_state_t *s) {
    uint8_t n = 0;
    for (uint8_t i = 0; i < s->n_chips; i++) n += s->up[i] ? 1 : 0;
    return n;
}
