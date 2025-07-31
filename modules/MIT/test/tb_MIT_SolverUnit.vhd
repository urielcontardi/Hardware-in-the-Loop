--! \file		tb_MIT_SolverUnit.vhd
--!
--! \brief		Testbench for the MIT_SolverUnit
--!
--! \author		Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       01-08-2025
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
--!				- 1.0	01-08-2025	<urielcontardi@hotmail.com>
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
use work.MIT_Pkg.all;

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity tb_MIT_SolverUnit is
End entity;

Architecture behavior of tb_MIT_SolverUnit is

    --------------------------------------------------------------------------
    -- Clock definition
    --------------------------------------------------------------------------
    constant CLK_FREQUENCY  : integer   := 200e6;
    constant CLK_PERIOD     : time      := 1 sec / CLK_FREQUENCY;

    --------------------------------------------------------------------------
    -- Testbench definition
    --------------------------------------------------------------------------
    -- UUT Generics
    constant N_SS           : natural := 5;    -- Number of State Space
    constant N_IN           : natural := 2;    -- Inputs number of State Space
    
    constant AVEC          : vector_fp_t(0 to N_SS - 1):= ( to_fp(1.0), to_fp(2.0), to_fp(3.0), to_fp(4.0), to_fp(5.0) );
    constant XVEC          : vector_fp_t(0 to N_SS - 1):= ( to_fp(-6.0), to_fp(-7.0), to_fp(-8.0), to_fp(-9.0), to_fp(-10.0) );
    constant YVEC          : vector_fp_t(0 to N_SS - 1):= ( to_fp(-1.0), to_fp(-1.0), to_fp(-1.0), to_fp(-1.0), to_fp(-1.0) );
    constant BVEC          : vector_fp_t(0 to N_IN - 1):= ( to_fp(11.0), to_fp(12.0));
    constant UVEC          : vector_fp_t(0 to N_IN - 1):= ( to_fp(13.0), to_fp(14.0));

    --------------------------------------------------------------------------
    -- UUT ports
    --------------------------------------------------------------------------
    -- Inputs
    signal sysclk          : std_logic := '0';
    signal reset_n         : std_logic := '0';
    signal start_i         : std_logic := '0';
    signal Avec_i          : vector_fp_t(0 to N_SS - 1):= ( to_fp(0.0), to_fp(0.0), to_fp(0.0), to_fp(0.0), to_fp(0.0) );
    signal Xvec_i          : vector_fp_t(0 to N_SS - 1):= ( to_fp(0.0), to_fp(0.0), to_fp(0.0), to_fp(0.0), to_fp(0.0) );
    signal Yvec_i          : vector_fp_t(0 to N_SS - 1):= ( to_fp(0.0), to_fp(0.0), to_fp(0.0), to_fp(0.0), to_fp(0.0) );
    signal Bvec_i          : vector_fp_t(0 to N_IN - 1):= ( to_fp(0.0), to_fp(0.0));
    signal Uvec_i          : vector_fp_t(0 to N_IN - 1):= ( to_fp(0.0), to_fp(0.0));
    signal stateResult_o   : fixed_point_data_t;
    signal busy_o          : std_logic;

Begin

    --------------------------------------------------------------------------
    -- Clk generation
    --------------------------------------------------------------------------
    sysclk <= not sysclk after CLK_PERIOD/2;

    --------------------------------------------------------------------------
    -- UUT
    --------------------------------------------------------------------------
    uut: Entity WORK.MIT_SolverUnit
    Generic map (
        N_SS    =>  N_SS,
        N_IN    =>  N_IN
    )
    Port map(
        sysclk          => sysclk,
        start_i         => start_i,
        Avec_i          => Avec_i,
        Xvec_i          => Xvec_i,
        Yvec_i          => Yvec_i,
        Bvec_i          => Bvec_i,
        Uvec_i          => Uvec_i,
        stateResult_o   => stateResult_o,
        busy_o          => busy_o
    );

    --------------------------------------------------------------------------
    -- Stimulus process
    --------------------------------------------------------------------------
    stimulus: process
    begin
        wait for CLK_PERIOD * 5;
        wait until rising_edge(sysclk);
        reset_n <= '1';
        wait for CLK_PERIOD * 2;

        --------------------------------------------------------------------------
        -- Stimulus
        --------------------------------------------------------------------------
        start_i <= '1';
        Avec_i <= AVEC;
        Xvec_i <= XVEC;
        Yvec_i <= YVEC;
        Bvec_i <= BVEC;
        Uvec_i <= UVEC;
        wait for CLK_PERIOD;
        start_i <= '0'; 

        wait for CLK_PERIOD * 50;

        finish;
    end process;

End architecture;
