--! \file		StateSolver_tb.vhd
--!
--! \brief		
--!
--! \author		Uriel Abe Contardi (contardii@weg.net)
--! \date       24-06-2024
--!
--! \version    1.0
--!
--! \copyright	Copyright (c) 2024 WEG - All Rights reserved.
--!
--! \note		Target devices : No specific target
--! \note		Tool versions  : No specific tool
--! \note		Dependencies   : No specific dependencies
--!
--! \ingroup	WCW
--! \warning	None
--!
--! \note		Revisions:
--!				- 1.0	24-06-2024	<contardii@weg.net>
--!				First revision.
--------------------------------------------------------------------------
-- Default libraries
--------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use std.textio.all;

--------------------------------------------------------------------------
-- User packages
--------------------------------------------------------------------------
use work.Solver_pkg.all;

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity StateSolver_tb is
End entity;

Architecture behavior of StateSolver_tb is

    --------------------------------------------------------------------------
    -- Cosntants definition
    --------------------------------------------------------------------------
    constant CLK_FREQUENCY  : integer   := 160e6;
    constant CLK_PERIOD     : time      := 1 sec / CLK_FREQUENCY;
    constant N_SS           : natural   := 5; -- Number of State Space
    constant N_IN           : natural   := 2; -- Inputs number of State Space

    --------------------------------------------------------------------------
    -- Factors
    --------------------------------------------------------------------------
    constant FACTORS       : vector_fp_t(0 to N_SS + N_IN - 1) := (
        x"00000002", x"00000003", x"00000004", x"00000005", x"00000006",
        x"00000007" , x"00000008" 
    );

    --------------------------------------------------------------------------
    -- UUT ports
    --------------------------------------------------------------------------
    -- Inputs
    signal sysclk  : std_logic := '0';
    signal reset_n : std_logic := '0';
    signal init_i  : std_logic := '0';
    signal a_vec_i : vector_fp_t(0 to N_SS + N_IN - 1) := FACTORS;
    signal b_vec_i : vector_fp_t(0 to N_SS + N_IN - 1) := FACTORS;
    signal result_o : fixed_point_data_t;
    signal busy_o  : std_logic;

Begin

    --------------------------------------------------------------------------
    -- Clk generation
    --------------------------------------------------------------------------
    sysclk <= not sysclk after CLK_PERIOD/2;

    --------------------------------------------------------------------------
    -- Unit Under Test
    --------------------------------------------------------------------------
    UUT: Entity work.StateSolver
    Generic map(
        N_SS    => N_SS,
        N_IN    => N_IN
    )
    Port map(
        sysclk  => sysclk,
        reset_n => reset_n,
        init_i  => init_i, 
        a_vec_i => a_vec_i,
        b_vec_i => b_vec_i,
        result_o => result_o,
        busy_o  => busy_o 
    );

    --------------------------------------------------------------------------
    -- Stimulus
    --------------------------------------------------------------------------
    stimulus: process

        procedure  tickSignal (signal tick : out std_logic ) is
        begin
            tick <= '1';
            wait for CLK_PERIOD*1;
            tick <= '0';
        end procedure;

    begin
        wait for CLK_PERIOD * 5;
        wait until rising_edge(sysclk);
        reset_n <= '1';
        wait for CLK_PERIOD * 50;

        --------------------------------------------------------------------------
        -- Stimulus
        --------------------------------------------------------------------------
        tickSignal(init_i);
        wait for CLK_PERIOD *100;

    end process stimulus;

End architecture;
