-------------------------------------------------------------------------------
-- File:        VFProfile.vhd
--
-- Description: V/F Profile Calculator
--              Calculates voltage reference based on frequency using the
--              Volts-per-Hertz control law with low-speed boost compensation.
--
--              V/F Curve:
--              
--              V ^
--           Vn |................___________
--              |           ___/
--              |       ___/
--         Vb   |__+___/
--              |  |  /
--              |__|_/_____________________> f
--              0  fb                    fn
--
--              Equation:
--              V(f) = Vb + (Vn - Vb) * (f / fn)  for f <= fn
--              V(f) = Vn                          for f > fn (field weakening)
--
-- Author:      Uriel Abe Contardi (urielcontardi@hotmail.com)
-- Date:        12-02-2026
-- Version:     1.0
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.VFControlPkg.all;

entity VFProfile is
    generic (
        FREQ_WIDTH      : natural := 16;     -- Frequency input width
        VOLTAGE_WIDTH   : natural := 16;     -- Voltage output width (0-65535 = 0-100%)
        NOMINAL_FREQ    : natural := 6000;   -- Nominal frequency (0.01 Hz units) = 60 Hz
        BOOST_FREQ      : natural := 500;    -- Boost cutoff frequency (0.01 Hz) = 5 Hz
        BOOST_PERCENT   : natural := 5       -- Boost voltage as % of nominal
    );
    port (
        clk               : in  std_logic;
        rst_n             : in  std_logic;
        
        -- Frequency input
        freq_i            : in  std_logic_vector(FREQ_WIDTH-1 downto 0);
        
        -- Configuration (optional runtime adjustment)
        nominal_freq_i    : in  std_logic_vector(FREQ_WIDTH-1 downto 0);  -- 0 = use param
        boost_percent_i   : in  std_logic_vector(7 downto 0);             -- 0 = use param
        
        -- Voltage output
        voltage_o         : out std_logic_vector(VOLTAGE_WIDTH-1 downto 0);
        field_weakening_o : out std_logic
    );
end entity VFProfile;

architecture rtl of VFProfile is

    ---------------------------------------------------------------------------
    -- Local Constants
    ---------------------------------------------------------------------------
    constant MAX_VOLTAGE : unsigned(VOLTAGE_WIDTH-1 downto 0) := (others => '1');  -- 65535

    -- Pipeline stages for timing
    constant PIPE_STAGES : natural := 3;

    ---------------------------------------------------------------------------
    -- Internal Signals
    ---------------------------------------------------------------------------
    signal nom_freq        : unsigned(FREQ_WIDTH-1 downto 0);
    signal boost_pct       : unsigned(7 downto 0);
    signal freq_unsigned   : unsigned(FREQ_WIDTH-1 downto 0);
    
    signal boost_voltage   : unsigned(31 downto 0);
    signal linear_voltage  : unsigned(47 downto 0);
    signal final_voltage   : unsigned(31 downto 0);
    signal field_weak      : std_logic;
    
    -- Pipeline registers
    type voltage_pipe_t is array (0 to PIPE_STAGES-1) of unsigned(VOLTAGE_WIDTH-1 downto 0);
    type fw_pipe_t is array (0 to PIPE_STAGES-1) of std_logic;
    
    signal voltage_pipe : voltage_pipe_t;
    signal fw_pipe      : fw_pipe_t;

begin

    ---------------------------------------------------------------------------
    -- Input Conversion
    ---------------------------------------------------------------------------
    freq_unsigned <= unsigned(freq_i);

    ---------------------------------------------------------------------------
    -- Configuration Selection
    ---------------------------------------------------------------------------
    Config_Proc : process(nominal_freq_i, boost_percent_i)
    begin
        if unsigned(nominal_freq_i) /= 0 then
            nom_freq <= unsigned(nominal_freq_i);
        else
            nom_freq <= to_unsigned(NOMINAL_FREQ, FREQ_WIDTH);
        end if;
        
        if unsigned(boost_percent_i) /= 0 then
            boost_pct <= unsigned(boost_percent_i);
        else
            boost_pct <= to_unsigned(BOOST_PERCENT, 8);
        end if;
    end process;

    ---------------------------------------------------------------------------
    -- V/F Calculation (Combinational)
    ---------------------------------------------------------------------------
    VF_Calc_Proc : process(freq_unsigned, nom_freq, boost_pct)
        variable boost_v      : unsigned(31 downto 0);
        variable slope_v      : unsigned(31 downto 0);
        variable linear_v     : unsigned(47 downto 0);
        variable result_v     : unsigned(31 downto 0);
    begin
        -- Boost voltage = boost_percent * MAX_VOLTAGE / 100
        boost_v := resize(boost_pct * resize(MAX_VOLTAGE, 24), 32) / 100;
        boost_voltage <= boost_v;
        
        -- Check for field weakening (f > fn)
        if freq_unsigned >= nom_freq then
            -- Field weakening region: voltage constant at maximum
            final_voltage <= resize(MAX_VOLTAGE, 32);
            field_weak <= '1';
        else
            -- Linear V/F region with boost
            -- V = Vboost + ((Vmax - Vboost) * f) / fn
            slope_v := resize(MAX_VOLTAGE, 32) - boost_v;
            linear_v := resize(slope_v * freq_unsigned, 48);
            
            -- Divide by nominal frequency (avoid division by zero)
            if nom_freq /= 0 then
                result_v := boost_v + resize(linear_v / nom_freq, 32);
            else
                result_v := boost_v;
            end if;
            
            -- Saturate to maximum
            if result_v > resize(MAX_VOLTAGE, 32) then
                final_voltage <= resize(MAX_VOLTAGE, 32);
            else
                final_voltage <= result_v;
            end if;
            
            field_weak <= '0';
        end if;
    end process;

    ---------------------------------------------------------------------------
    -- Output Pipeline (for timing)
    ---------------------------------------------------------------------------
    Pipeline_Proc : process(clk, rst_n)
    begin
        if rst_n = '0' then
            for i in 0 to PIPE_STAGES-1 loop
                voltage_pipe(i) <= (others => '0');
                fw_pipe(i) <= '0';
            end loop;
        elsif rising_edge(clk) then
            -- Stage 0
            voltage_pipe(0) <= final_voltage(VOLTAGE_WIDTH-1 downto 0);
            fw_pipe(0) <= field_weak;
            
            -- Propagate through pipeline
            for i in 1 to PIPE_STAGES-1 loop
                voltage_pipe(i) <= voltage_pipe(i-1);
                fw_pipe(i) <= fw_pipe(i-1);
            end loop;
        end if;
    end process;

    ---------------------------------------------------------------------------
    -- Output Assignment
    ---------------------------------------------------------------------------
    voltage_o         <= std_logic_vector(voltage_pipe(PIPE_STAGES-1));
    field_weakening_o <= fw_pipe(PIPE_STAGES-1);

end architecture rtl;
