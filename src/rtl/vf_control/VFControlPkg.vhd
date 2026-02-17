-------------------------------------------------------------------------------
-- File:        VFControlPkg.vhd
--
-- Description: Package with types, constants, and parameters for V/F Control
--              Contains fixed-point definitions and utility functions
--
-- Author:      Uriel Abe Contardi (urielcontardi@hotmail.com)
-- Date:        12-02-2026
-- Version:     1.0
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

package VFControlPkg is

    ---------------------------------------------------------------------------
    -- Fixed-Point Configuration
    ---------------------------------------------------------------------------
    -- Q14.18 format: 14 integer bits (including sign), 18 fractional bits
    -- Range: approximately +/-8191.999996
    -- Resolution: ~3.8e-6
    constant FP_INT_BITS  : natural := 14;
    constant FP_FRAC_BITS : natural := 18;
    constant FP_WIDTH     : natural := FP_INT_BITS + FP_FRAC_BITS;  -- 32 bits

    -- Fixed-point subtype
    subtype fp_t is signed(FP_WIDTH-1 downto 0);

    ---------------------------------------------------------------------------
    -- Sine Lookup Table Configuration
    ---------------------------------------------------------------------------
    constant SINE_TABLE_BITS     : natural := 10;                       -- 1024 entries
    constant SINE_TABLE_SIZE     : natural := 2 ** SINE_TABLE_BITS;     -- 1024
    constant SINE_AMPLITUDE_BITS : natural := 16;                       -- 16-bit amplitude

    -- Phase accumulator configuration
    constant PHASE_ACC_BITS : natural := 32;  -- 32-bit phase accumulator

    ---------------------------------------------------------------------------
    -- V/F Profile Parameters (defaults)
    ---------------------------------------------------------------------------
    constant NOMINAL_FREQ_HZ_DEFAULT   : real := 60.0;      -- Nominal frequency (Hz)
    constant NOMINAL_VOLTAGE_V_DEFAULT : real := 380.0;     -- Nominal line voltage (V RMS)
    constant BOOST_VOLTAGE_V_DEFAULT   : real := 20.0;      -- Low-speed voltage boost (V)
    constant BOOST_FREQ_HZ_DEFAULT     : real := 5.0;       -- Boost cutoff frequency (Hz)

    ---------------------------------------------------------------------------
    -- Data Width Constants
    ---------------------------------------------------------------------------
    constant FREQ_WIDTH      : natural := 16;  -- Frequency word width
    constant AMPLITUDE_WIDTH : natural := 16;  -- Amplitude word width
    constant OUTPUT_WIDTH    : natural := 32;  -- Output data width

    ---------------------------------------------------------------------------
    -- Sine Lookup Table Type
    ---------------------------------------------------------------------------
    type sine_table_t is array (0 to SINE_TABLE_SIZE-1) of signed(SINE_AMPLITUDE_BITS-1 downto 0);

    ---------------------------------------------------------------------------
    -- Utility Functions
    ---------------------------------------------------------------------------
    
    -- Convert real to fixed-point
    function real_to_fp(value : real) return fp_t;
    
    -- Convert fixed-point to real (for simulation/debug)
    function fp_to_real(value : fp_t) return real;
    
    -- Fixed-point multiplication with proper scaling
    function fp_mult(a, b : fp_t) return fp_t;
    
    -- Saturating add for fixed-point
    function fp_sat_add(a, b : fp_t) return fp_t;
    
    -- Generate sine lookup table
    function init_sine_table return sine_table_t;
    
    -- Calculate ceiling of log2
    function clog2(n : natural) return natural;

end package VFControlPkg;

package body VFControlPkg is

    ---------------------------------------------------------------------------
    -- real_to_fp: Convert real to fixed-point
    ---------------------------------------------------------------------------
    function real_to_fp(value : real) return fp_t is
        constant SCALE : real := 2.0 ** FP_FRAC_BITS;
    begin
        return to_signed(integer(value * SCALE), FP_WIDTH);
    end function;

    ---------------------------------------------------------------------------
    -- fp_to_real: Convert fixed-point to real
    ---------------------------------------------------------------------------
    function fp_to_real(value : fp_t) return real is
        constant SCALE : real := 2.0 ** FP_FRAC_BITS;
    begin
        return real(to_integer(value)) / SCALE;
    end function;

    ---------------------------------------------------------------------------
    -- fp_mult: Fixed-point multiplication with scaling
    ---------------------------------------------------------------------------
    function fp_mult(a, b : fp_t) return fp_t is
        variable product : signed(2*FP_WIDTH-1 downto 0);
    begin
        product := a * b;
        return product(FP_WIDTH + FP_FRAC_BITS - 1 downto FP_FRAC_BITS);
    end function;

    ---------------------------------------------------------------------------
    -- fp_sat_add: Saturating addition
    ---------------------------------------------------------------------------
    function fp_sat_add(a, b : fp_t) return fp_t is
        variable sum : signed(FP_WIDTH downto 0);
        constant MAX_POS : fp_t := (FP_WIDTH-1 => '0', others => '1');
        constant MAX_NEG : fp_t := (FP_WIDTH-1 => '1', others => '0');
    begin
        sum := resize(a, FP_WIDTH+1) + resize(b, FP_WIDTH+1);
        -- Check for overflow
        if sum > resize(MAX_POS, FP_WIDTH+1) then
            return MAX_POS;
        elsif sum < resize(MAX_NEG, FP_WIDTH+1) then
            return MAX_NEG;
        else
            return sum(FP_WIDTH-1 downto 0);
        end if;
    end function;

    ---------------------------------------------------------------------------
    -- init_sine_table: Generate sine lookup table
    ---------------------------------------------------------------------------
    function init_sine_table return sine_table_t is
        variable table : sine_table_t;
        variable angle : real;
        variable sine_val : real;
    begin
        for i in 0 to SINE_TABLE_SIZE-1 loop
            angle := 2.0 * MATH_PI * real(i) / real(SINE_TABLE_SIZE);
            sine_val := sin(angle) * real(2**(SINE_AMPLITUDE_BITS-1) - 1);
            table(i) := to_signed(integer(sine_val), SINE_AMPLITUDE_BITS);
        end loop;
        return table;
    end function;

    ---------------------------------------------------------------------------
    -- clog2: Ceiling of log base 2
    ---------------------------------------------------------------------------
    function clog2(n : natural) return natural is
        variable result : natural := 0;
        variable value  : natural := n - 1;
    begin
        while value > 0 loop
            result := result + 1;
            value := value / 2;
        end loop;
        return result;
    end function;

end package body VFControlPkg;
