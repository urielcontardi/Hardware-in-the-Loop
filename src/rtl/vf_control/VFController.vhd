-------------------------------------------------------------------------------
-- File:        VFController.vhd
--
-- Description: Top-Level V/F (Volts-per-Hertz) Controller
--              Integrates acceleration ramp, V/F profile, and 3-phase DDS
--              to provide complete scalar control for induction motors.
--
--              Architecture:
--              +-------------------------------------------------------------+
--              |                    VF_Controller                            |
--              |                                                             |
--              |  +------------+   f_actual   +------------+   amplitude    |
--              |  | AccelRamp  +------------->| VFProfile  +----------+     |
--              |  +------^-----+              +------------+          |     |
--              |         | f_ref                                      v     |
--              |         |                    +------------+    +----------+|
--              |  Control|                    | DDS3Phase  |<---| Scaler   ||
--              |  Input  |                    |            |    +----------+|
--              |         |                    +-----+------+                |
--              |                                    | Va,Vb,Vc              |
--              +------------------------------------+------------------------+
--                                                   v
--                                            To PWM/Modulator
--
--              Features:
--              - Complete V/F control with configurable parameters
--              - Smooth acceleration/deceleration ramps
--              - Low-speed voltage boost for starting torque
--              - Forward/reverse direction control
--              - Status monitoring outputs
--
-- Author:      Uriel Abe Contardi (urielcontardi@hotmail.com)
-- Date:        12-02-2026
-- Version:     1.0
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.VFControlPkg.all;

entity VFController is
    generic (
        -- System Configuration
        CLK_FREQ_HZ      : natural := 200_000_000;  -- System clock frequency
        
        -- Ramp Configuration  
        RAMP_UPDATE_HZ   : natural := 1000;         -- Ramp update rate (Hz)
        
        -- V/F Profile Configuration
        NOMINAL_FREQ     : natural := 6000;         -- Nominal freq (0.01 Hz) = 60 Hz
        BOOST_FREQ       : natural := 500;          -- Boost freq (0.01 Hz) = 5 Hz
        BOOST_PERCENT    : natural := 5;            -- Boost voltage percentage
        
        -- DDS Configuration
        PHASE_ACC_BITS   : natural := 32;           -- Phase accumulator bits
        TABLE_ADDR_BITS  : natural := 10;           -- Sine table size (2^10 = 1024)
        OUTPUT_WIDTH     : natural := 32;           -- Output voltage width
        
        -- Data Widths
        FREQ_WIDTH       : natural := 16;           -- Frequency word width
        AMPLITUDE_WIDTH  : natural := 16            -- Amplitude word width
    );
    port (
        clk               : in  std_logic;
        rst_n             : in  std_logic;
        
        -----------------------------------------------------------------------
        -- Control Interface
        -----------------------------------------------------------------------
        enable_i          : in  std_logic;
        direction_i       : in  std_logic;  -- 0 = forward, 1 = reverse
        freq_ref_i        : in  std_logic_vector(FREQ_WIDTH-1 downto 0);
        accel_rate_i      : in  std_logic_vector(FREQ_WIDTH-1 downto 0);  -- Q8.8 Hz/s
        decel_rate_i      : in  std_logic_vector(FREQ_WIDTH-1 downto 0);  -- Q8.8 Hz/s
        
        -----------------------------------------------------------------------
        -- Optional Configuration
        -----------------------------------------------------------------------
        nom_freq_cfg_i    : in  std_logic_vector(FREQ_WIDTH-1 downto 0);  -- 0 = use param
        boost_pct_cfg_i   : in  std_logic_vector(7 downto 0);             -- 0 = use param
        
        -----------------------------------------------------------------------
        -- Three-Phase Voltage Outputs (to PWM Modulator)
        -----------------------------------------------------------------------
        va_ref_o          : out std_logic_vector(OUTPUT_WIDTH-1 downto 0);
        vb_ref_o          : out std_logic_vector(OUTPUT_WIDTH-1 downto 0);
        vc_ref_o          : out std_logic_vector(OUTPUT_WIDTH-1 downto 0);
        
        -----------------------------------------------------------------------
        -- Status Outputs
        -----------------------------------------------------------------------
        freq_actual_o     : out std_logic_vector(FREQ_WIDTH-1 downto 0);
        voltage_ref_o     : out std_logic_vector(AMPLITUDE_WIDTH-1 downto 0);
        running_o         : out std_logic;
        ramping_o         : out std_logic;
        at_setpoint_o     : out std_logic;
        field_weakening_o : out std_logic;
        
        -----------------------------------------------------------------------
        -- Synchronization Outputs
        -----------------------------------------------------------------------
        zero_cross_a_o    : out std_logic;
        sync_o            : out std_logic
    );
end entity VFController;

architecture rtl of VFController is

    ---------------------------------------------------------------------------
    -- Internal Signals
    ---------------------------------------------------------------------------
    signal freq_ramped        : std_logic_vector(FREQ_WIDTH-1 downto 0);
    signal voltage_amplitude  : std_logic_vector(AMPLITUDE_WIDTH-1 downto 0);
    signal ramp_ramping       : std_logic;
    signal ramp_at_setpoint   : std_logic;
    signal vf_field_weakening : std_logic;

begin

    ---------------------------------------------------------------------------
    -- Acceleration Ramp Module
    ---------------------------------------------------------------------------
    AccelRamp_Inst : entity work.AccelRamp
    generic map (
        CLK_FREQ_HZ    => CLK_FREQ_HZ,
        UPDATE_FREQ_HZ => RAMP_UPDATE_HZ,
        FREQ_WIDTH     => FREQ_WIDTH,
        RATE_WIDTH     => FREQ_WIDTH
    )
    port map (
        clk            => clk,
        rst_n          => rst_n,
        enable_i       => enable_i,
        freq_target_i  => freq_ref_i,
        accel_rate_i   => accel_rate_i,
        decel_rate_i   => decel_rate_i,
        freq_actual_o  => freq_ramped,
        ramping_o      => ramp_ramping,
        at_setpoint_o  => ramp_at_setpoint
    );

    ---------------------------------------------------------------------------
    -- V/F Profile Calculator
    ---------------------------------------------------------------------------
    VFProfile_Inst : entity work.VFProfile
    generic map (
        FREQ_WIDTH     => FREQ_WIDTH,
        VOLTAGE_WIDTH  => AMPLITUDE_WIDTH,
        NOMINAL_FREQ   => NOMINAL_FREQ,
        BOOST_FREQ     => BOOST_FREQ,
        BOOST_PERCENT  => BOOST_PERCENT
    )
    port map (
        clk               => clk,
        rst_n             => rst_n,
        freq_i            => freq_ramped,
        nominal_freq_i    => nom_freq_cfg_i,
        boost_percent_i   => boost_pct_cfg_i,
        voltage_o         => voltage_amplitude,
        field_weakening_o => vf_field_weakening
    );

    ---------------------------------------------------------------------------
    -- Three-Phase DDS Generator
    ---------------------------------------------------------------------------
    DDS3Phase_Inst : entity work.DDS3Phase
    generic map (
        CLK_FREQ_HZ      => CLK_FREQ_HZ,
        PHASE_ACC_BITS   => PHASE_ACC_BITS,
        TABLE_ADDR_BITS  => TABLE_ADDR_BITS,
        OUTPUT_WIDTH     => OUTPUT_WIDTH,
        AMPLITUDE_WIDTH  => AMPLITUDE_WIDTH
    )
    port map (
        clk            => clk,
        rst_n          => rst_n,
        enable_i       => enable_i,
        direction_i    => direction_i,
        freq_i         => freq_ramped,
        amplitude_i    => voltage_amplitude,
        va_o           => va_ref_o,
        vb_o           => vb_ref_o,
        vc_o           => vc_ref_o,
        zero_cross_a_o => zero_cross_a_o,
        sync_o         => sync_o
    );

    ---------------------------------------------------------------------------
    -- Status Output Assignment
    ---------------------------------------------------------------------------
    freq_actual_o     <= freq_ramped;
    voltage_ref_o     <= voltage_amplitude;
    running_o         <= enable_i when unsigned(freq_ramped) /= 0 else '0';
    ramping_o         <= ramp_ramping;
    at_setpoint_o     <= ramp_at_setpoint;
    field_weakening_o <= vf_field_weakening;

end architecture rtl;
