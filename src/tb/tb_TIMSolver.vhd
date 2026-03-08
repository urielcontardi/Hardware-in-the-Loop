--! \file		tb_TIMSolver.vhd
--!
--! \brief		
--!
--! \author		Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       06-08-2025
--!
--! \version    1.0
--!
--! \copyright	Copyright (c) 2025 - All Rights reserved.
--!
--! \note		Target devices : No specific target
--! \note		Tool versions  : No specific tool
--! \note		Dependencies   : No specific dependencies
--!
--! \ingroup	None
--! \warning	None
--!
--! \note		Revisions:
--!				- 1.0	06-08-2025	<urielcontardi@hotmail.com>
--!				First revision.
--------------------------------------------------------------------------
-- Default libraries
--------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use std.textio.all;
use std.env.finish;

--------------------------------------------------------------------------
-- User packages
--------------------------------------------------------------------------
use work.BilinearSolverPkg.all;

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity tb_TIMSolver is
End entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
Architecture behavior of tb_TIMSolver is

    --------------------------------------------------------------------------
    -- Clock definition
    --------------------------------------------------------------------------
    constant CLK_FREQUENCY : integer := 200e6;
    constant CLK_PERIOD    : time    := 1 sec / CLK_FREQUENCY;

    --------------------------------------------------------------------------
    -- Testbench parameters
    --------------------------------------------------------------------------
    constant DATA_WIDTH          : natural := 42;  -- Data width for fixed-point representation

    constant DISCRETIZATION_STEP : real    := 100.0e-9;     -- Discretization step
    constant rs                  : real    := 0.0;          -- Stator resistance
    constant rr                  : real    := 0.2826;       -- Rotor resistance
    constant ls                  : real    := 3.1364e-3;    -- Stator inductance
    constant lr                  : real    := 6.3264e-3;    -- Rotor inductance
    constant lm                  : real    := 109.9442e-3;  -- Mutual inductance
    constant j                   : real    := 0.192;        -- Moment of inertia
    constant npp                 : real    := 2.0;          -- Number of poles

    --------------------------------------------------------------------------
    -- Testbench definition
    --------------------------------------------------------------------------
    signal sysclk                : std_logic := '0';
    signal reset_n               : std_logic := '0';
    signal va_i                  : std_logic_vector(DATA_WIDTH-1 downto 0) := to_fp(0.0);
    signal vb_i                  : std_logic_vector(DATA_WIDTH-1 downto 0) := to_fp(0.0);
    signal vc_i                  : std_logic_vector(DATA_WIDTH-1 downto 0) := to_fp(0.0);
    signal torque_load_i         : std_logic_vector(DATA_WIDTH-1 downto 0) := to_fp(0.0);
    signal ialpha_o              : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal ibeta_o               : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal flux_rotor_alpha_o    : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal flux_rotor_beta_o     : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal speed_mech_o          : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal data_valid_o          : std_logic;    -- Output data valid flag

Begin

    --------------------------------------------------------------------------
    -- Clk generation
    --------------------------------------------------------------------------
    sysclk <= not sysclk after CLK_PERIOD/2;

    --------------------------------------------------------------------------
    -- UUT
    --------------------------------------------------------------------------
    uut: Entity WORK.TIM_Solver
    Generic map(
        CLOCK_FREQUENCY     => CLK_FREQUENCY,
        Ts                  => DISCRETIZATION_STEP,
        rs                  => rs,           
        rr                  => rr,           
        ls                  => ls,           
        lr                  => lr,           
        lm                  => lm,           
        j                   => j,            
        npp                 => npp     
    )
    Port map(
        sysclk              => sysclk,
        reset_n             => reset_n,
        va_i                => va_i,                
        vb_i                => vb_i,                
        vc_i                => vc_i,                
        torque_load_i       => torque_load_i,       
        ialpha_o            => ialpha_o,             
        ibeta_o             => ibeta_o,                
        flux_rotor_alpha_o  => flux_rotor_alpha_o, 
        flux_rotor_beta_o   => flux_rotor_beta_o,       
        speed_mech_o        => speed_mech_o,        
        data_valid_o        => data_valid_o
    );

    --------------------------------------------------------------------------
    -- Stimulus
    --------------------------------------------------------------------------
    stimulus: process
    begin
        wait for CLK_PERIOD * 5;
        wait until rising_edge(sysclk);
        reset_n <= '1';
        wait for CLK_PERIOD * 5;

        -- Apply test inputs
        va_i                  <= to_fp(100.0);
        vb_i                  <= to_fp(300.0);
        vc_i                  <= to_fp(-400.0);
        torque_load_i         <= to_fp(0.0);
        
        wait for CLK_PERIOD * 50;
        finish;
    end process ;

End architecture;
