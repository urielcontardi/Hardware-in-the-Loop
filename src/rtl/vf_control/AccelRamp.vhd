-------------------------------------------------------------------------------
-- File:        AccelRamp.vhd
--
-- Description: Acceleration/Deceleration Ramp Generator
--              Smoothly transitions frequency reference from current value
--              to target value at configurable acceleration/deceleration rates.
--
--              Features:
--              - Separate acceleration and deceleration rates
--              - Linear ramping with configurable update period
--              - At-setpoint detection with hysteresis
--              - Enable/disable control
--
-- Author:      Uriel Abe Contardi (urielcontardi@hotmail.com)
-- Date:        12-02-2026
-- Version:     1.0
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.VFControlPkg.all;

entity AccelRamp is
    generic (
        CLK_FREQ_HZ    : natural := 200_000_000;  -- System clock frequency
        UPDATE_FREQ_HZ : natural := 1000;         -- Ramp update frequency (Hz)
        FREQ_WIDTH     : natural := 16;           -- Frequency word width
        RATE_WIDTH     : natural := 16            -- Rate word width (Q8.8 Hz/s)
    );
    port (
        clk             : in  std_logic;
        rst_n           : in  std_logic;
        
        -- Control inputs
        enable_i        : in  std_logic;                              -- Enable ramping
        freq_target_i   : in  std_logic_vector(FREQ_WIDTH-1 downto 0); -- Target freq (0.01 Hz)
        accel_rate_i    : in  std_logic_vector(RATE_WIDTH-1 downto 0); -- Accel rate (Q8.8 Hz/s)
        decel_rate_i    : in  std_logic_vector(RATE_WIDTH-1 downto 0); -- Decel rate (Q8.8 Hz/s)
        
        -- Outputs
        freq_actual_o   : out std_logic_vector(FREQ_WIDTH-1 downto 0); -- Actual frequency
        ramping_o       : out std_logic;                               -- Currently ramping
        at_setpoint_o   : out std_logic                                -- At target frequency
    );
end entity AccelRamp;

architecture rtl of AccelRamp is

    ---------------------------------------------------------------------------
    -- Local Constants
    ---------------------------------------------------------------------------
    constant UPDATE_PERIOD : natural := CLK_FREQ_HZ / UPDATE_FREQ_HZ;
    constant TIMER_WIDTH   : natural := clog2(UPDATE_PERIOD + 1);
    
    -- Hysteresis for at-setpoint detection (0.1 Hz = 10 counts at 0.01Hz resolution)
    constant HYSTERESIS : unsigned(FREQ_WIDTH-1 downto 0) := to_unsigned(10, FREQ_WIDTH);

    -- Rate multiplication factor (convert Hz to 0.01 Hz units)
    constant RATE_MULT : natural := 100;

    ---------------------------------------------------------------------------
    -- Internal Signals
    ---------------------------------------------------------------------------
    signal update_timer : unsigned(TIMER_WIDTH-1 downto 0);
    signal update_tick  : std_logic;
    
    signal freq_current : unsigned(FREQ_WIDTH-1 downto 0);
    signal freq_target  : unsigned(FREQ_WIDTH-1 downto 0);
    signal freq_delta   : unsigned(FREQ_WIDTH-1 downto 0);
    
    signal accel_increment : unsigned(31 downto 0);
    signal decel_increment : unsigned(31 downto 0);
    
    signal accelerating : std_logic;
    signal decelerating : std_logic;

begin

    ---------------------------------------------------------------------------
    -- Input Conversion
    ---------------------------------------------------------------------------
    freq_target <= unsigned(freq_target_i);

    ---------------------------------------------------------------------------
    -- Update Timer
    ---------------------------------------------------------------------------
    Timer_Proc : process(clk, rst_n)
    begin
        if rst_n = '0' then
            update_timer <= (others => '0');
            update_tick  <= '0';
        elsif rising_edge(clk) then
            if update_timer >= UPDATE_PERIOD - 1 then
                update_timer <= (others => '0');
                update_tick  <= '1';
            else
                update_timer <= update_timer + 1;
                update_tick  <= '0';
            end if;
        end if;
    end process;

    ---------------------------------------------------------------------------
    -- Rate to Increment Conversion
    -- accel_rate is Q8.8, so actual rate = accel_rate_i / 256
    -- increment = (rate / 256) * RATE_MULT / UPDATE_FREQ_HZ
    ---------------------------------------------------------------------------
    Increment_Proc : process(accel_rate_i, decel_rate_i)
        variable accel_temp : unsigned(31 downto 0);
        variable decel_temp : unsigned(31 downto 0);
    begin
        -- Calculate increments
        accel_temp := resize(unsigned(accel_rate_i) * RATE_MULT, 32);
        accel_temp := shift_right(accel_temp, 8);  -- Divide by 256 (Q8.8 to integer)
        
        decel_temp := resize(unsigned(decel_rate_i) * RATE_MULT, 32);
        decel_temp := shift_right(decel_temp, 8);
        
        -- Minimum increment of 1 to ensure progress
        if accel_temp = 0 and unsigned(accel_rate_i) /= 0 then
            accel_increment <= to_unsigned(1, 32);
        else
            accel_increment <= accel_temp;
        end if;
        
        if decel_temp = 0 and unsigned(decel_rate_i) /= 0 then
            decel_increment <= to_unsigned(1, 32);
        else
            decel_increment <= decel_temp;
        end if;
    end process;

    ---------------------------------------------------------------------------
    -- Ramp State Machine
    ---------------------------------------------------------------------------
    Ramp_Proc : process(clk, rst_n)
        variable diff : unsigned(FREQ_WIDTH-1 downto 0);
    begin
        if rst_n = '0' then
            freq_current <= (others => '0');
        elsif rising_edge(clk) then
            if enable_i = '0' then
                -- When disabled, immediately go to zero
                freq_current <= (others => '0');
            elsif update_tick = '1' then
                if freq_current < freq_target then
                    -- Accelerating
                    diff := freq_target - freq_current;
                    if diff > accel_increment(FREQ_WIDTH-1 downto 0) then
                        freq_current <= freq_current + accel_increment(FREQ_WIDTH-1 downto 0);
                    else
                        freq_current <= freq_target;
                    end if;
                elsif freq_current > freq_target then
                    -- Decelerating
                    diff := freq_current - freq_target;
                    if diff > decel_increment(FREQ_WIDTH-1 downto 0) then
                        freq_current <= freq_current - decel_increment(FREQ_WIDTH-1 downto 0);
                    else
                        freq_current <= freq_target;
                    end if;
                end if;
            end if;
        end if;
    end process;

    ---------------------------------------------------------------------------
    -- Status Signals
    ---------------------------------------------------------------------------
    Status_Proc : process(freq_current, freq_target)
    begin
        -- Calculate absolute difference
        if freq_current >= freq_target then
            freq_delta <= freq_current - freq_target;
        else
            freq_delta <= freq_target - freq_current;
        end if;
        
        -- Ramping status
        if freq_current < freq_target then
            accelerating <= '1';
            decelerating <= '0';
        elsif freq_current > freq_target then
            accelerating <= '0';
            decelerating <= '1';
        else
            accelerating <= '0';
            decelerating <= '0';
        end if;
    end process;

    -- At setpoint with hysteresis
    at_setpoint_o <= '1' when freq_delta <= HYSTERESIS else '0';
    
    -- Ramping output
    ramping_o <= accelerating or decelerating;

    ---------------------------------------------------------------------------
    -- Output Assignment
    ---------------------------------------------------------------------------
    freq_actual_o <= std_logic_vector(freq_current);

end architecture rtl;
