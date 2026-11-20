// Host test for mcp23017_matrix.c with a fake MCP23017 (IOCON.BANK=0 register
// model, sequential addressing). Build and run: see Makefile (`make test`).
#include <stdio.h>
#include <string.h>

#include "matrix_config.h"
#include "mcp23017_matrix.h"

static int failures, checks;
#define CHECK(cond, ...)                                  \
    do {                                                  \
        checks++;                                         \
        if (!(cond)) {                                    \
            failures++;                                   \
            printf("FAIL %s:%d: ", __FILE__, __LINE__);   \
            printf(__VA_ARGS__);                          \
            printf("\n");                                 \
        }                                                 \
    } while (0)

// ---- fake extender ---------------------------------------------------------
typedef struct {
    bool present;
    uint8_t iodir[2], gppu[2], olat[2];
} fake_chip_t;
typedef struct {
    uint8_t row_pin, col_pin;
} press_t;
typedef struct {
    fake_chip_t chip[MX_MAX_CHIPS]; // index = addr - 0x20
    press_t pressed[MX_MAX_CHIPS][8];
    uint8_t n_pressed[MX_MAX_CHIPS];
    int calls[MX_MAX_CHIPS]; // bus calls per address, including failed ones
} fake_t;

static void fake_reset_chip(fake_chip_t *c) {
    c->iodir[0] = c->iodir[1] = 0xFF; // power-on: all inputs
    c->gppu[0] = c->gppu[1] = 0;
    c->olat[0] = c->olat[1] = 0;
}
static void fake_init(fake_t *f) {
    memset(f, 0, sizeof *f);
    for (int i = 0; i < MX_MAX_CHIPS; i++) fake_reset_chip(&f->chip[i]);
}
static uint16_t u16(const uint8_t *p) { return (uint16_t)p[0] | ((uint16_t)p[1] << 8); }

static uint16_t pin_levels(const fake_t *f, int ci) {
    const fake_chip_t *c = &f->chip[ci];
    uint16_t iodir = u16(c->iodir), gppu = u16(c->gppu), olat = u16(c->olat), v = 0;
    for (int p = 0; p < 16; p++) {
        uint16_t b = (uint16_t)1 << p;
        int level;
        if (!(iodir & b)) level = (olat & b) != 0;      // output: drives OLAT
        else level = (gppu & b) != 0;                   // input: pull-up or floating(0)
        if ((iodir & b) && (gppu & b)) {
            for (int k = 0; k < f->n_pressed[ci]; k++) {
                uint16_t rb = (uint16_t)1 << f->pressed[ci][k].row_pin;
                if (f->pressed[ci][k].col_pin == p && !(iodir & rb) && !(olat & rb)) level = 0; // diode conducts, row low
            }
        }
        if (level) v |= b;
    }
    return v;
}

// BANK=0 map: register r covers port A (even) / B (odd); sequential access
// auto-increments, so 2 bytes at the A register cover both ports.
static uint8_t *reg_ptr(fake_chip_t *c, uint8_t reg) {
    switch (reg) {
        case 0x00: return &c->iodir[0];
        case 0x01: return &c->iodir[1];
        case 0x0C: return &c->gppu[0];
        case 0x0D: return &c->gppu[1];
        case 0x12: case 0x14: return &c->olat[0]; // GPIO write -> OLAT
        case 0x13: case 0x15: return &c->olat[1];
        default: return 0;
    }
}
static bool fake_write(void *ctx, uint8_t addr, uint8_t reg, const uint8_t *d, uint8_t len) {
    fake_t *f = ctx;
    if (addr < 0x20 || addr > 0x27) return false;
    f->calls[addr - 0x20]++;
    if (!f->chip[addr - 0x20].present) return false;
    for (uint8_t i = 0; i < len; i++) {
        uint8_t *p = reg_ptr(&f->chip[addr - 0x20], reg + i);
        if (!p) return false; // unmodelled register: treat as NACK so a wrong address fails loudly
        *p = d[i];
    }
    return true;
}
static bool fake_read(void *ctx, uint8_t addr, uint8_t reg, uint8_t *d, uint8_t len) {
    fake_t *f = ctx;
    if (addr < 0x20 || addr > 0x27) return false;
    f->calls[addr - 0x20]++;
    if (!f->chip[addr - 0x20].present) return false;
    if (reg != 0x12 || len != 2) return false; // only GPIO reads are modelled
    uint16_t v = pin_levels(f, addr - 0x20);
    d[0] = v & 0xFF;
    d[1] = v >> 8;
    return true;
}
static void press(fake_t *f, int ci, uint8_t row_pin, uint8_t col_pin) {
    f->pressed[ci][f->n_pressed[ci]++] = (press_t){row_pin, col_pin};
}

// ---- helpers ---------------------------------------------------------------
static mx_bus_t bus_for(fake_t *f) { return (mx_bus_t){fake_write, fake_read, f}; }
static bool key(const mx_row_t *m, int r, int c) { return (m[r] >> c) & 1; }
static int count_keys(const mx_row_t *m) {
    int n = 0;
    for (int r = 0; r < MX_LOGICAL_ROWS; r++) n += __builtin_popcount(m[r]);
    return n;
}

// ---- tests -----------------------------------------------------------------
static void test_validate(void) {
    CHECK(mx_validate(mx_chips, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) == 0, "placeholder config must validate");
    mx_chip_cfg_t bad[2];
    memcpy(bad, mx_chips, sizeof bad);
    bad[1].addr = 0x20;
    CHECK(mx_validate(bad, 2, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "duplicate address must be rejected");
    memcpy(bad, mx_chips, sizeof bad);
    bad[0].col_pins[0] = 0; // also a row pin
    CHECK(mx_validate(bad, 2, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "pin as both row and column must be rejected");
    memcpy(bad, mx_chips, sizeof bad);
    bad[0].addr = 0x30;
    CHECK(mx_validate(bad, 2, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "address outside 0x20..0x27 must be rejected");
    memcpy(bad, mx_chips, sizeof bad);
    bad[0].col_pins[4] = 15; // GPB7 as a column: output-only pin
    CHECK(mx_validate(bad, 2, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "column on GPB7 must be rejected");
    bad[0].col_pins[4] = 7;  // GPA7
    CHECK(mx_validate(bad, 2, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "column on GPA7 must be rejected");
    memcpy(bad, mx_chips, sizeof bad);
    bad[0].row_pins[3] = 7;  // GPA7 as a row is fine
    CHECK(mx_validate(bad, 2, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) == 0, "row on GPA7 must be accepted");
    CHECK(mx_validate(mx_chips, 2, 4, 9) != 0, "map entry outside logical size must be rejected");
}

static void test_init_registers(void) {
    fake_t f;
    fake_init(&f);
    f.chip[0].present = f.chip[1].present = true;
    mx_bus_t bus = bus_for(&f);
    mx_state_t s;
    mx_init(&s, &bus, mx_chips, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS);
    CHECK(mx_chips_up(&s) == 2, "both chips up, got %u", mx_chips_up(&s));
    CHECK(f.chip[0].iodir[0] == 0xF0 && f.chip[0].iodir[1] == 0xFF, "IODIR: rows GPA0-3 out, rest in; got %02X %02X", f.chip[0].iodir[0], f.chip[0].iodir[1]);
    CHECK(f.chip[0].gppu[0] == 0x00 && f.chip[0].gppu[1] == 0x1F, "GPPU: cols GPB0-4 pulled up; got %02X %02X", f.chip[0].gppu[0], f.chip[0].gppu[1]);
    CHECK(f.chip[0].olat[0] == 0xFF && f.chip[0].olat[1] == 0xFF, "rows start high");
}

static void test_keys_at_logical_positions(void) {
    fake_t f;
    fake_init(&f);
    f.chip[0].present = f.chip[1].present = true;
    mx_bus_t bus = bus_for(&f);
    mx_state_t s;
    mx_init(&s, &bus, mx_chips, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS);
    mx_row_t m[MX_LOGICAL_ROWS];

    CHECK(!mx_scan(&s, m) && count_keys(m) == 0, "idle matrix is empty and unchanged");

    // Expected positions are hand-derived from the placeholder table, not read back from it.
    press(&f, 0, 1, 10); // chip0 row GPA1, col GPB2 -> logical (1,2)
    press(&f, 1, 3, 8);  // chip1 row GPA3, col GPB0 -> logical (3,9)
    press(&f, 1, 0, 12); // chip1 row GPA0, col GPB4 -> logical (0,5)
    CHECK(mx_scan(&s, m), "first press reports a change");
    CHECK(count_keys(m) == 3, "exactly 3 keys, got %d", count_keys(m));
    CHECK(key(m, 1, 2), "chip0 (A1,B2) -> (1,2)");
    CHECK(key(m, 3, 9), "chip1 (A3,B0) -> (3,9)");
    CHECK(key(m, 0, 5), "chip1 (A0,B4) -> (0,5)");
    CHECK(!mx_scan(&s, m), "steady state reports no change");
}

static void test_missing_chip(void) {
    fake_t f;
    fake_init(&f);
    f.chip[0].present = true; // chip 1 (0x21) absent
    mx_bus_t bus = bus_for(&f);
    mx_state_t s;
    mx_init(&s, &bus, mx_chips, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS);
    CHECK(mx_chips_up(&s) == 1, "only chip 0 up");
    press(&f, 0, 1, 10);
    press(&f, 1, 3, 8); // key on the absent chip: must never appear
    mx_row_t m[MX_LOGICAL_ROWS];
    mx_scan(&s, m);
    CHECK(count_keys(m) == 1 && key(m, 1, 2), "present chip works, absent chip gives no keys");
    int base = f.calls[1];
    for (int i = 0; i < 254; i++) mx_scan(&s, m);
    CHECK(f.calls[1] == base, "no bus traffic to a down chip between retries (%d extra)", f.calls[1] - base);
    CHECK(count_keys(m) == 1, "keys stable while chip down");

    // Retry: chip appears, next retry boundary reinitialises it. Down chip came
    // up with its register state reset, as after a real power-up.
    f.chip[1].present = true;
    int n = 0;
    while (!s.up[1] && n < 600) {
        mx_scan(&s, m);
        n++;
    }
    CHECK(s.up[1] && n <= 256, "chip reinitialised within one retry period, took %d scans", n);
    mx_scan(&s, m);
    CHECK(count_keys(m) == 2 && key(m, 3, 9), "keys of the revived chip appear");
    CHECK(f.chip[1].iodir[0] == 0xF0 && f.chip[1].gppu[1] == 0x1F, "revived chip was reconfigured");
}

static void test_chip_dies_midrun(void) {
    fake_t f;
    fake_init(&f);
    f.chip[0].present = f.chip[1].present = true;
    mx_bus_t bus = bus_for(&f);
    mx_state_t s;
    mx_init(&s, &bus, mx_chips, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS);
    press(&f, 0, 1, 10);
    press(&f, 1, 3, 8);
    mx_row_t m[MX_LOGICAL_ROWS];
    mx_scan(&s, m);
    CHECK(count_keys(m) == 2, "both keys seen");
    f.chip[1].present = false; // piece cut off or unplugged
    CHECK(mx_scan(&s, m), "loss of a key is a change");
    CHECK(count_keys(m) == 1 && key(m, 1, 2) && !key(m, 3, 9), "dead chip's key released, other chip unaffected");
    CHECK(!s.up[1], "chip marked down");
    // power-cycled piece comes back with default registers
    fake_reset_chip(&f.chip[1]);
    f.chip[1].present = true;
    for (int i = 0; i < 256; i++) mx_scan(&s, m);
    mx_scan(&s, m);
    CHECK(s.up[1] && count_keys(m) == 2, "chip rejoins after a retry period");
}

static void test_all_down_no_hang(void) {
    fake_t f;
    fake_init(&f);
    mx_bus_t bus = bus_for(&f);
    mx_state_t s;
    mx_init(&s, &bus, mx_chips, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS);
    mx_row_t m[MX_LOGICAL_ROWS];
    for (int i = 0; i < 2000; i++) mx_scan(&s, m); // returns, i.e. no hang
    CHECK(count_keys(m) == 0 && mx_chips_up(&s) == 0, "no chips: empty matrix");
    CHECK(f.calls[0] < 20 && f.calls[1] < 20, "bounded bus traffic with all chips down (%d, %d calls)", f.calls[0], f.calls[1]);
}

int main(void) {
    test_validate();
    test_init_registers();
    test_keys_at_logical_positions();
    test_missing_chip();
    test_chip_dies_midrun();
    test_all_down_no_hang();
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
