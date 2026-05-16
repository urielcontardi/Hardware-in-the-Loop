-- IIRFilter.vhd
--
-- First-order IIR low-pass filter (single-pole, multiplier-less).
-- Used as anti-aliasing pre-filter in the AXI Stream decimator path.
--
-- Difference equation (leaky integrator form):
--     y[k+1] = y[k] + α·(x[k] - y[k])
--
-- With α = 1/2^ALPHA_BITS the multiplication by α becomes a right-shift.
-- An extended-precision accumulator avoids the truncation problem of the
-- naive shift-only filter — the integrator retains the bottom ALPHA_BITS
-- so small input deltas still accumulate (no "stuck" output).
--
-- Cutoff frequency (small-α approximation):
--     fc = 1 / (2π·τ),   τ ≈ Ts · 2^ALPHA_BITS
--
-- At Ts = 270 ns (3.704 MHz solver step) and ALPHA_BITS = 9:
--     τ ≈ 138 µs,   fc ≈ 1.15 kHz
-- Anti-aliasing for the 3.7 MHz → 10 kHz decimator (Nyquist 5 kHz). PWM ripple
-- itself is filtered ~45× by the motor inductance in the solver path (confirmed
-- by the offline cocotb simulation), so a heavier IIR is not needed.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity IIRFilter is
    Generic (
        DATA_WIDTH : natural := 42;
        ALPHA_BITS : natural := 9    -- α = 1 / 2^ALPHA_BITS
    );
    Port (
        clk        : in  std_logic;
        reset_n    : in  std_logic;
        data_valid : in  std_logic;  -- pulse to advance one filter step
        x_i        : in  std_logic_vector(DATA_WIDTH-1 downto 0);
        y_o        : out std_logic_vector(DATA_WIDTH-1 downto 0)
    );
end entity;

architecture rtl of IIRFilter is
    constant ACC_WIDTH : natural := DATA_WIDTH + ALPHA_BITS;
    signal acc : signed(ACC_WIDTH-1 downto 0) := (others => '0');
begin
    -- y = top DATA_WIDTH bits of acc (= acc / 2^ALPHA_BITS, signed arith shift)
    y_o <= std_logic_vector(acc(ACC_WIDTH-1 downto ALPHA_BITS));

    process(clk, reset_n)
    begin
        if reset_n = '0' then
            acc <= (others => '0');
        elsif rising_edge(clk) then
            if data_valid = '1' then
                -- acc' = acc + (x - y),  where y = acc / 2^ALPHA_BITS
                acc <= acc
                     + resize(signed(x_i), ACC_WIDTH)
                     - resize(acc(ACC_WIDTH-1 downto ALPHA_BITS), ACC_WIDTH);
            end if;
        end if;
    end process;
end architecture;
