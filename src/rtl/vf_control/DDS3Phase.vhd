-------------------------------------------------------------------------------
-- File:        DDS3Phase.vhd
--
-- Description: Three-Phase Direct Digital Synthesis (DDS) Generator
--              Generates balanced 3-phase sinusoidal waveforms with 120 deg 
--              phase displacement using a single sine lookup table.
--
--              Features:
--              - Single sine LUT shared for all 3 phases (120 deg offset)
--              - Configurable frequency via phase increment
--              - Configurable amplitude scaling
--              - Direction control (forward/reverse rotation)
--              - High resolution phase accumulator (32-bit)
--
--              Phase Relationships:
--              - Phase A: 0 deg    (reference)
--              - Phase B: -120 deg (lagging for forward rotation)
--              - Phase C: +120 deg (leading for forward rotation)
--
-- Author:      Uriel Abe Contardi (urielcontardi@hotmail.com)
-- Date:        12-02-2026
-- Version:     1.0
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

use work.VFControlPkg.all;

entity DDS3Phase is
    generic (
        CLK_FREQ_HZ      : natural := 200_000_000;  -- System clock frequency
        PHASE_ACC_BITS   : natural := 32;           -- Phase accumulator width
        TABLE_ADDR_BITS  : natural := 10;           -- Sine table address bits (1024)
        OUTPUT_WIDTH     : natural := 32;           -- Output data width (signed)
        AMPLITUDE_WIDTH  : natural := 16            -- Amplitude control width
    );
    port (
        clk             : in  std_logic;
        rst_n           : in  std_logic;
        
        -- Control inputs
        enable_i        : in  std_logic;
        direction_i     : in  std_logic;                                -- 0=fwd, 1=rev
        freq_i          : in  std_logic_vector(15 downto 0);            -- Freq (0.01 Hz)
        amplitude_i     : in  std_logic_vector(AMPLITUDE_WIDTH-1 downto 0);
        
        -- Three-phase outputs (signed, scaled by amplitude)
        va_o            : out std_logic_vector(OUTPUT_WIDTH-1 downto 0);
        vb_o            : out std_logic_vector(OUTPUT_WIDTH-1 downto 0);
        vc_o            : out std_logic_vector(OUTPUT_WIDTH-1 downto 0);
        
        -- Synchronization outputs
        zero_cross_a_o  : out std_logic;
        sync_o          : out std_logic
    );
end entity DDS3Phase;

architecture rtl of DDS3Phase is

    ---------------------------------------------------------------------------
    -- Local Constants
    ---------------------------------------------------------------------------
    constant TABLE_SIZE : natural := 2 ** TABLE_ADDR_BITS;  -- 1024 entries
    constant SINE_BITS  : natural := 16;                     -- Sine table data width
    
    -- Phase offsets for 3-phase (in phase accumulator units)
    -- 120 deg = 2^PHASE_ACC_BITS / 3
    constant PHASE_120 : unsigned(PHASE_ACC_BITS-1 downto 0) := 
        to_unsigned(integer(real(2**PHASE_ACC_BITS) / 3.0), PHASE_ACC_BITS);
    constant PHASE_240 : unsigned(PHASE_ACC_BITS-1 downto 0) := 
        shift_left(PHASE_120, 1);  -- 2 * PHASE_120

    ---------------------------------------------------------------------------
    -- Sine Lookup Table
    ---------------------------------------------------------------------------
    type sine_lut_t is array (0 to TABLE_SIZE-1) of signed(SINE_BITS-1 downto 0);
    
    function init_sine_lut return sine_lut_t is
        variable lut : sine_lut_t;
        variable angle : real;
        variable sine_val : real;
    begin
        for i in 0 to TABLE_SIZE-1 loop
            angle := 2.0 * MATH_PI * real(i) / real(TABLE_SIZE);
            sine_val := sin(angle) * real(2**(SINE_BITS-1) - 1);
            lut(i) := to_signed(integer(sine_val), SINE_BITS);
        end loop;
        return lut;
    end function;
    
    constant SINE_LUT : sine_lut_t := init_sine_lut;

    ---------------------------------------------------------------------------
    -- Internal Signals
    ---------------------------------------------------------------------------
    signal phase_acc     : unsigned(PHASE_ACC_BITS-1 downto 0) := (others => '0');
    signal phase_inc     : unsigned(PHASE_ACC_BITS-1 downto 0) := (others => '0');
    signal phase_a       : unsigned(PHASE_ACC_BITS-1 downto 0) := (others => '0');
    signal phase_b       : unsigned(PHASE_ACC_BITS-1 downto 0) := (others => '0');
    signal phase_c       : unsigned(PHASE_ACC_BITS-1 downto 0) := (others => '0');
    
    signal addr_a        : unsigned(TABLE_ADDR_BITS-1 downto 0) := (others => '0');
    signal addr_b        : unsigned(TABLE_ADDR_BITS-1 downto 0) := (others => '0');
    signal addr_c        : unsigned(TABLE_ADDR_BITS-1 downto 0) := (others => '0');
    
    signal sine_a        : signed(SINE_BITS-1 downto 0) := (others => '0');
    signal sine_b        : signed(SINE_BITS-1 downto 0) := (others => '0');
    signal sine_c        : signed(SINE_BITS-1 downto 0) := (others => '0');
    
    signal scaled_a      : signed(SINE_BITS+AMPLITUDE_WIDTH-1 downto 0) := (others => '0');
    signal scaled_b      : signed(SINE_BITS+AMPLITUDE_WIDTH-1 downto 0) := (others => '0');
    signal scaled_c      : signed(SINE_BITS+AMPLITUDE_WIDTH-1 downto 0) := (others => '0');
    
    signal prev_phase_msb : std_logic;
    
    -- For phase increment calculation
    signal freq_unsigned : unsigned(15 downto 0) := (others => '0');

    -- Pre-compute multiplier to avoid overflow
    -- PHASE_MULT = floor(2^48 / (100 * CLK_FREQ_HZ))
    -- For 200 MHz: 2^48 / 20e9 = 14073.748...
    constant PHASE_MULT : natural := integer((2.0**32) * (2.0**16) / (100.0 * real(CLK_FREQ_HZ)));

begin

    ---------------------------------------------------------------------------
    -- Input Conversion
    ---------------------------------------------------------------------------
    freq_unsigned <= unsigned(freq_i);

    ---------------------------------------------------------------------------
    -- Phase Increment Calculation
    -- phase_inc = freq_i * 2^32 / (100 * CLK_FREQ_HZ)
    -- For 200 MHz: At 60 Hz (freq_i = 6000): phase_inc = 6000 * 4294967296 / 20000000000
    --            = 1288.49 (approximately)
    --
    -- To avoid integer overflow, we pre-compute:
    -- PHASE_MULT = 2^32 / (100 * CLK_FREQ_HZ) * 2^16 (scaled for precision)
    -- phase_inc = (freq * PHASE_MULT) >> 16
    ---------------------------------------------------------------------------
    PhaseInc_Proc : process(clk, rst_n)
        variable freq_val : natural;
        variable product  : natural;
    begin
        if rst_n = '0' then
            phase_inc <= (others => '0');
        elsif rising_edge(clk) then
            -- Guard against metavalues in frequency input
            if Is_X(freq_i) then
                phase_inc <= (others => '0');
            else
                -- Simple calculation using naturals
                freq_val := to_integer(freq_unsigned);
                product  := freq_val * PHASE_MULT;
                phase_inc <= to_unsigned(product / 65536, PHASE_ACC_BITS);  -- >> 16
            end if;
        end if;
    end process;

    ---------------------------------------------------------------------------
    -- Phase Accumulator
    ---------------------------------------------------------------------------
    PhaseAcc_Proc : process(clk, rst_n)
    begin
        if rst_n = '0' then
            phase_acc <= (others => '0');
            prev_phase_msb <= '0';
        elsif rising_edge(clk) then
            if enable_i = '0' then
                phase_acc <= (others => '0');
                prev_phase_msb <= '0';
            else
                phase_acc <= phase_acc + phase_inc;
                prev_phase_msb <= phase_acc(PHASE_ACC_BITS-1);
            end if;
        end if;
    end process;

    ---------------------------------------------------------------------------
    -- Phase Calculation for Each Phase
    ---------------------------------------------------------------------------
    PhaseCalc_Proc : process(phase_acc, direction_i)
    begin
        phase_a <= phase_acc;
        
        if direction_i = '1' then
            -- Reverse rotation: ABC -> ACB
            phase_b <= phase_acc + PHASE_240;  -- +240 deg = -120 deg
            phase_c <= phase_acc + PHASE_120;  -- +120 deg
        else
            -- Forward rotation: ABC
            phase_b <= phase_acc - PHASE_120;  -- -120 deg
            phase_c <= phase_acc + PHASE_120;  -- +120 deg
        end if;
    end process;

    ---------------------------------------------------------------------------
    -- Table Address Extraction (MSBs of phase)
    ---------------------------------------------------------------------------
    addr_a <= phase_a(PHASE_ACC_BITS-1 downto PHASE_ACC_BITS-TABLE_ADDR_BITS);
    addr_b <= phase_b(PHASE_ACC_BITS-1 downto PHASE_ACC_BITS-TABLE_ADDR_BITS);
    addr_c <= phase_c(PHASE_ACC_BITS-1 downto PHASE_ACC_BITS-TABLE_ADDR_BITS);

    ---------------------------------------------------------------------------
    -- Sine Table Lookup (Registered for timing)
    ---------------------------------------------------------------------------
    SineLUT_Proc : process(clk, rst_n)
    begin
        if rst_n = '0' then
            sine_a <= (others => '0');
            sine_b <= (others => '0');
            sine_c <= (others => '0');
        elsif rising_edge(clk) then
            -- Guard against metavalues in address signals
            if Is_X(std_logic_vector(addr_a)) then
                sine_a <= (others => '0');
            else
                sine_a <= SINE_LUT(to_integer(addr_a));
            end if;
            
            if Is_X(std_logic_vector(addr_b)) then
                sine_b <= (others => '0');
            else
                sine_b <= SINE_LUT(to_integer(addr_b));
            end if;
            
            if Is_X(std_logic_vector(addr_c)) then
                sine_c <= (others => '0');
            else
                sine_c <= SINE_LUT(to_integer(addr_c));
            end if;
        end if;
    end process;

    ---------------------------------------------------------------------------
    -- Amplitude Scaling
    -- output = (sine * amplitude) >> (AMPLITUDE_WIDTH - 1)
    ---------------------------------------------------------------------------
    Scaling_Proc : process(clk, rst_n)
        variable amp_signed : signed(AMPLITUDE_WIDTH downto 0);
    begin
        if rst_n = '0' then
            scaled_a <= (others => '0');
            scaled_b <= (others => '0');
            scaled_c <= (others => '0');
        elsif rising_edge(clk) then
            if enable_i = '0' then
                scaled_a <= (others => '0');
                scaled_b <= (others => '0');
                scaled_c <= (others => '0');
            elsif Is_X(amplitude_i) or Is_X(std_logic_vector(sine_a)) or
                  Is_X(std_logic_vector(sine_b)) or Is_X(std_logic_vector(sine_c)) then
                -- Guard against metavalues
                scaled_a <= (others => '0');
                scaled_b <= (others => '0');
                scaled_c <= (others => '0');
            else
                amp_signed := signed('0' & amplitude_i);
                -- Resize after shift to match output width (multiply produces SINE_BITS+AMPLITUDE_WIDTH+1 bits)
                scaled_a <= resize(shift_right(sine_a * amp_signed, AMPLITUDE_WIDTH - 1), scaled_a'length);
                scaled_b <= resize(shift_right(sine_b * amp_signed, AMPLITUDE_WIDTH - 1), scaled_b'length);
                scaled_c <= resize(shift_right(sine_c * amp_signed, AMPLITUDE_WIDTH - 1), scaled_c'length);
            end if;
        end if;
    end process;

    ---------------------------------------------------------------------------
    -- Output Assignment (Sign-extend to OUTPUT_WIDTH)
    ---------------------------------------------------------------------------
    va_o <= std_logic_vector(resize(scaled_a, OUTPUT_WIDTH));
    vb_o <= std_logic_vector(resize(scaled_b, OUTPUT_WIDTH));
    vc_o <= std_logic_vector(resize(scaled_c, OUTPUT_WIDTH));

    ---------------------------------------------------------------------------
    -- Synchronization Outputs
    ---------------------------------------------------------------------------
    SyncOut_Proc : process(clk, rst_n)
    begin
        if rst_n = '0' then
            zero_cross_a_o <= '0';
            sync_o <= '0';
        elsif rising_edge(clk) then
            -- Zero crossing: phase wraps from negative to positive
            -- Detect when MSB changes from 1 to 0
            if prev_phase_msb = '1' and phase_acc(PHASE_ACC_BITS-1) = '0' then
                zero_cross_a_o <= '1';
            else
                zero_cross_a_o <= '0';
            end if;
            
            -- Sync pulse: phase accumulator near zero
            if phase_acc < phase_inc then
                sync_o <= '1';
            else
                sync_o <= '0';
            end if;
        end if;
    end process;

end architecture rtl;
