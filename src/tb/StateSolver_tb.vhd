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
    constant VECTOR1      : vector_fp_t(0 to N_SS - 1) := (
        x"00000002", x"00000003", x"00000004", x"00000005", x"00000006"
    );

    constant VECTOR2      : vector_fp_t(0 to N_IN - 1) := (
        x"00000008", x"00000009"
    );

    --------------------------------------------------------------------------
    -- UUT ports
    --------------------------------------------------------------------------
    signal sysclk       : std_logic := '0';
    signal reset_n      : std_logic := '0';
    signal valid_i      : std_logic := '0';
    signal busy_o       : std_logic;
    signal AVec_i      : vector_fp_t(0 to N_SS - 1) := VECTOR1;
    signal XVec_i      : vector_fp_t(0 to N_SS - 1) := VECTOR1;
    signal BVec_i      : vector_fp_t(0 to N_IN - 1) := VECTOR2;
    signal UVec_i      : vector_fp_t(0 to N_IN - 1) := VECTOR2;
    signal XdVec_o     : fixed_point_data_t;

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
        valid_i => valid_i,
        busy_o  => busy_o,
        AVec_i  => AVec_i,
        XVec_i  => XVec_i,
        BVec_i  => BVec_i,
        UVec_i  => UVec_i,
        XdVec_o => XdVec_o
    );

    --------------------------------------------------------------------------
    -- Stimulus
    --------------------------------------------------------------------------
    Stimulus: process

        procedure  tickSignal (signal tick : out std_logic ) is
        begin
            tick <= '1';
            wait for CLK_PERIOD*1;
            tick <= '0';
        end procedure;

    Begin
        wait for CLK_PERIOD * 5;
        wait until rising_edge(sysclk);
        reset_n <= '1';
        wait for CLK_PERIOD * 50;

        --------------------------------------------------------------------------
        -- Stimulus
        --------------------------------------------------------------------------
        tickSignal(valid_i);
        wait for CLK_PERIOD *100;

    End process;

End architecture;
