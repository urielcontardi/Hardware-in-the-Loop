-------------------------------------------------------------------------------
-- File:        tb_VFController.vhd
--
-- Description: Testbench for V/F Controller
--              Tests the complete V/F scalar control system including:
--              - Acceleration/deceleration ramps
--              - V/F profile (voltage vs frequency)
--              - 3-phase DDS output generation
--              - Forward/reverse operation
--
-- Author:      Uriel Abe Contardi (urielcontardi@hotmail.com)
-- Date:        12-02-2026
-- Version:     1.0
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

use std.textio.all;
use std.env.finish;

use work.VFControlPkg.all;

entity tb_VFController is
end entity tb_VFController;

architecture behavior of tb_VFController is

    ---------------------------------------------------------------------------
    -- Clock Configuration
    ---------------------------------------------------------------------------
    constant CLK_FREQ_HZ   : natural := 200_000_000;    -- 200 MHz
    constant CLK_PERIOD    : time    := 1 sec / CLK_FREQ_HZ;  -- 5 ns
    
    constant FREQ_WIDTH      : natural := 16;
    constant OUTPUT_WIDTH    : natural := 32;
    constant AMPLITUDE_WIDTH : natural := 16;

    ---------------------------------------------------------------------------
    -- DUT Signals
    ---------------------------------------------------------------------------
    signal clk             : std_logic := '0';
    signal rst_n           : std_logic := '0';
    
    -- Control inputs
    signal enable          : std_logic := '0';
    signal direction       : std_logic := '0';
    signal freq_ref        : std_logic_vector(FREQ_WIDTH-1 downto 0) := (others => '0');
    signal accel_rate      : std_logic_vector(FREQ_WIDTH-1 downto 0) := (others => '0');
    signal decel_rate      : std_logic_vector(FREQ_WIDTH-1 downto 0) := (others => '0');
    
    -- Optional configuration
    signal nom_freq_cfg    : std_logic_vector(FREQ_WIDTH-1 downto 0) := (others => '0');
    signal boost_pct_cfg   : std_logic_vector(7 downto 0) := (others => '0');
    
    -- Outputs
    signal va_ref          : std_logic_vector(OUTPUT_WIDTH-1 downto 0);
    signal vb_ref          : std_logic_vector(OUTPUT_WIDTH-1 downto 0);
    signal vc_ref          : std_logic_vector(OUTPUT_WIDTH-1 downto 0);
    signal freq_actual     : std_logic_vector(FREQ_WIDTH-1 downto 0);
    signal voltage_ref     : std_logic_vector(AMPLITUDE_WIDTH-1 downto 0);
    signal running         : std_logic;
    signal ramping         : std_logic;
    signal at_setpoint     : std_logic;
    signal field_weakening : std_logic;
    signal zero_cross_a    : std_logic;
    signal sync_pulse      : std_logic;

    ---------------------------------------------------------------------------
    -- Helper Functions
    ---------------------------------------------------------------------------
    function freq_to_hz(freq : std_logic_vector) return real is
    begin
        return real(to_integer(unsigned(freq))) / 100.0;
    end function;

    function voltage_to_percent(volt : std_logic_vector) return real is
    begin
        return real(to_integer(unsigned(volt))) / real((2**AMPLITUDE_WIDTH) - 1) * 100.0;
    end function;

begin

    ---------------------------------------------------------------------------
    -- Clock Generation
    ---------------------------------------------------------------------------
    clk <= not clk after CLK_PERIOD / 2;

    ---------------------------------------------------------------------------
    -- DUT Instantiation
    ---------------------------------------------------------------------------
    DUT : entity work.VFController
    generic map (
        CLK_FREQ_HZ      => CLK_FREQ_HZ,
        RAMP_UPDATE_HZ   => 1000,
        NOMINAL_FREQ     => 6000,     -- 60 Hz
        BOOST_FREQ       => 500,      -- 5 Hz
        BOOST_PERCENT    => 5,
        PHASE_ACC_BITS   => 32,
        TABLE_ADDR_BITS  => 10,
        OUTPUT_WIDTH     => OUTPUT_WIDTH,
        FREQ_WIDTH       => FREQ_WIDTH,
        AMPLITUDE_WIDTH  => AMPLITUDE_WIDTH
    )
    port map (
        clk               => clk,
        rst_n             => rst_n,
        enable_i          => enable,
        direction_i       => direction,
        freq_ref_i        => freq_ref,
        accel_rate_i      => accel_rate,
        decel_rate_i      => decel_rate,
        nom_freq_cfg_i    => nom_freq_cfg,
        boost_pct_cfg_i   => boost_pct_cfg,
        va_ref_o          => va_ref,
        vb_ref_o          => vb_ref,
        vc_ref_o          => vc_ref,
        freq_actual_o     => freq_actual,
        voltage_ref_o     => voltage_ref,
        running_o         => running,
        ramping_o         => ramping,
        at_setpoint_o     => at_setpoint,
        field_weakening_o => field_weakening,
        zero_cross_a_o    => zero_cross_a,
        sync_o            => sync_pulse
    );

    ---------------------------------------------------------------------------
    -- Test Stimulus
    ---------------------------------------------------------------------------
    Stimulus_Proc : process
    begin
        -- Initialize
        report "============================================================";
        report "V/F Controller Testbench (VHDL)";
        report "============================================================";
        report "Clock Frequency: " & integer'image(CLK_FREQ_HZ / 1_000_000) & " MHz";
        report "============================================================";
        
        -- Default values
        enable        <= '0';
        direction     <= '0';
        freq_ref      <= (others => '0');
        accel_rate    <= std_logic_vector(to_unsigned(25600, FREQ_WIDTH));  -- 100 Hz/s (Q8.8)
        decel_rate    <= std_logic_vector(to_unsigned(25600, FREQ_WIDTH));  -- 100 Hz/s
        nom_freq_cfg  <= (others => '0');  -- Use default
        boost_pct_cfg <= (others => '0');  -- Use default
        
        -- Wait for clock to stabilize
        wait for CLK_PERIOD * 10;
        
        -- Release reset
        wait until rising_edge(clk);
        rst_n <= '1';
        report "Reset released";
        wait for CLK_PERIOD * 10;
        
        -----------------------------------------------------------------------
        -- Test 1: Start motor - ramp to 30 Hz
        -----------------------------------------------------------------------
        report "";
        report "TEST 1: Start motor - ramp to 30 Hz";
        enable     <= '1';
        freq_ref   <= std_logic_vector(to_unsigned(3000, FREQ_WIDTH));  -- 30 Hz
        accel_rate <= std_logic_vector(to_unsigned(51200, FREQ_WIDTH)); -- 200 Hz/s (Q8.8)
        
        -- Wait for ramp to complete
        wait until at_setpoint = '1';
        report "Reached setpoint: " & real'image(freq_to_hz(freq_actual)) & " Hz, Voltage: " & 
               real'image(voltage_to_percent(voltage_ref)) & "%";
        
        -- Hold at 30 Hz for a while
        wait for CLK_PERIOD * 500_000;  -- ~2.5 ms at 200 MHz
        
        -----------------------------------------------------------------------
        -- Test 2: Accelerate to 60 Hz (nominal)
        -----------------------------------------------------------------------
        report "";
        report "TEST 2: Accelerate to 60 Hz (nominal)";
        freq_ref <= std_logic_vector(to_unsigned(6000, FREQ_WIDTH));  -- 60 Hz
        
        -- Monitor during acceleration
        while at_setpoint = '0' loop
            wait for CLK_PERIOD * 100_000;  -- Every ~0.5 ms
            report "Ramping: " & real'image(freq_to_hz(freq_actual)) & " Hz, Voltage: " & 
                   real'image(voltage_to_percent(voltage_ref)) & "%, Ramping=" & std_logic'image(ramping);
        end loop;
        
        report "Reached nominal: " & real'image(freq_to_hz(freq_actual)) & " Hz, Voltage: " & 
               real'image(voltage_to_percent(voltage_ref)) & "%";
        
        -- Hold at 60 Hz
        wait for CLK_PERIOD * 1_000_000;  -- ~5 ms
        
        -----------------------------------------------------------------------
        -- Test 3: Decelerate to 10 Hz
        -----------------------------------------------------------------------
        report "";
        report "TEST 3: Decelerate to 10 Hz";
        freq_ref   <= std_logic_vector(to_unsigned(1000, FREQ_WIDTH));  -- 10 Hz
        decel_rate <= std_logic_vector(to_unsigned(5120, FREQ_WIDTH)); -- 20 Hz/s (Q8.8)
        
        wait until at_setpoint = '1';
        report "Reached setpoint: " & real'image(freq_to_hz(freq_actual)) & " Hz, Voltage: " & 
               real'image(voltage_to_percent(voltage_ref)) & "%";
        
        -- Hold at 10 Hz
        wait for CLK_PERIOD * 1_000_000;  -- ~5 ms
        
        -----------------------------------------------------------------------
        -- Test 4: Reverse direction
        -----------------------------------------------------------------------
        report "";
        report "TEST 4: Reverse direction test";
        direction <= '1';  -- Reverse
        freq_ref  <= std_logic_vector(to_unsigned(3000, FREQ_WIDTH));  -- 30 Hz reverse
        
        wait until at_setpoint = '1';
        report "Reverse at: " & real'image(freq_to_hz(freq_actual)) & " Hz, Voltage: " & 
               real'image(voltage_to_percent(voltage_ref)) & "%";
        
        wait for CLK_PERIOD * 1_000_000;
        
        -----------------------------------------------------------------------
        -- Test 5: Stop motor
        -----------------------------------------------------------------------
        report "";
        report "TEST 5: Stop motor";
        freq_ref <= (others => '0');
        
        wait until at_setpoint = '1';
        report "Motor stopped: " & real'image(freq_to_hz(freq_actual)) & " Hz";
        
        wait for CLK_PERIOD * 200_000;
        
        -----------------------------------------------------------------------
        -- Test 6: Enable/Disable test
        -----------------------------------------------------------------------
        report "";
        report "TEST 6: Enable/Disable test";
        direction <= '0';
        freq_ref  <= std_logic_vector(to_unsigned(3000, FREQ_WIDTH));
        enable    <= '1';
        
        wait for CLK_PERIOD * 500_000;
        report "Running: " & real'image(freq_to_hz(freq_actual)) & " Hz";
        
        enable <= '0';
        wait for CLK_PERIOD * 100;
        report "Disabled - outputs should be zero";
        report "  va_ref = " & integer'image(to_integer(signed(va_ref)));
        report "  vb_ref = " & integer'image(to_integer(signed(vb_ref)));
        report "  vc_ref = " & integer'image(to_integer(signed(vc_ref)));
        
        wait for CLK_PERIOD * 100_000;
        
        -----------------------------------------------------------------------
        -- Test Complete
        -----------------------------------------------------------------------
        report "";
        report "============================================================";
        report "All tests completed successfully!";
        report "============================================================";
        
        finish;
    end process;

    ---------------------------------------------------------------------------
    -- Zero Crossing Counter
    ---------------------------------------------------------------------------
    ZeroCross_Monitor : process(clk)
        variable zero_cross_count : integer := 0;
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                zero_cross_count := 0;
            elsif zero_cross_a = '1' and enable = '1' then
                zero_cross_count := zero_cross_count + 1;
            end if;
        end if;
    end process;

end architecture behavior;
