# Host test: `make test` (needs only a C compiler; override with CC=clang).
# The test also parses the spec's CSV blocks (read-only, SPEC below) and checks
# matrix_config.h against them.
# `make mutants` is the negative control: it builds copies of the module or config
# with a deliberate fault (wrong register address, row/col index swap, rows driven
# high, row pull-ups on, a wrong config pin) and succeeds only if the test FAILS
# on every one.
CC ?= cc
CFLAGS = -std=c11 -Wall -Wextra -Werror -O1
# Spec the table is checked against; path is relative to this directory.
SPEC ?= ../docs/rev1-spec.md
BUILD = build

test: $(BUILD)/test_matrix
	./$(BUILD)/test_matrix

$(BUILD)/test_matrix: test_matrix.c mcp23017_matrix.c mcp23017_matrix.h matrix_config.h
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -DSPEC_PATH='"$(SPEC)"' -I. test_matrix.c mcp23017_matrix.c -o $@

mutants:
	@mkdir -p $(BUILD)
	@set -e; for m in gppu_reg gpio_reg iodir_reg rowcol_swap rows_driven_high row_pullups cfg_row_pin; do \
	  case $$m in \
	    gppu_reg) file=mcp23017_matrix.h; e='s/MX_REG_GPPUA  = 0x0C/MX_REG_GPPUA  = 0x0E/';; \
	    gpio_reg) file=mcp23017_matrix.h; e='s/MX_REG_GPIOA  = 0x12/MX_REG_GPIOA  = 0x13/';; \
	    iodir_reg) file=mcp23017_matrix.h; e='s/MX_REG_IODIRA = 0x00/MX_REG_IODIRA = 0x01/';; \
	    rowcol_swap) file=mcp23017_matrix.c; e='s/c->map\[r \* c->n_cols + k\]/c->map[k * c->n_rows + r]/';; \
	    rows_driven_high) file=mcp23017_matrix.c; e='s/uint16_t olat = (uint16_t)~pin_mask(c->row_pins, c->n_rows);/uint16_t olat = 0xFFFF;/; s/dir \&= (uint16_t)~((uint16_t)1 << c->row_pins\[active_row\]);/dir \&= (uint16_t)~pin_mask(c->row_pins, c->n_rows);/';; \
	    row_pullups) file=mcp23017_matrix.c; e='s/uint16_t cols = pin_mask(c->col_pins, c->n_cols);/uint16_t cols = pin_mask(c->col_pins, c->n_cols) | pin_mask(c->row_pins, c->n_rows);/';; \
	    cfg_row_pin) file=matrix_config.h; e='/addr = 0x24/s/row_pins = {0, 1, 2, 3, 4}/row_pins = {0, 1, 2, 3, 5}/';; \
	  esac; \
	  mkdir -p $(BUILD)/$$m; cp mcp23017_matrix.h mcp23017_matrix.c matrix_config.h test_matrix.c $(BUILD)/$$m/; \
	  sed -i.bak "$$e" $(BUILD)/$$m/$$file; \
	  if cmp -s $(BUILD)/$$m/$$file $$file; then echo "mutant $$m: sed did not change the source"; exit 2; fi; \
	  $(CC) $(CFLAGS) -DSPEC_PATH='"$(SPEC)"' -I$(BUILD)/$$m $(BUILD)/$$m/test_matrix.c $(BUILD)/$$m/mcp23017_matrix.c -o $(BUILD)/$$m/t; \
	  if $(BUILD)/$$m/t > $(BUILD)/$$m/log 2>&1; then echo "mutant $$m: SURVIVED (test passed, bad)"; exit 1; else echo "mutant $$m: killed ($$(rg -c '^FAIL' $(BUILD)/$$m/log || true) failing checks)"; fi; \
	done

clean:
	rm -rf $(BUILD)

.PHONY: test mutants clean
