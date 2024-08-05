--! \file		StateSpaceSolver_tb.vhd
--!
--! \brief		
--!
--! \author		Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       22-07-2024
--!
--! \version    1.0
--!
--! \copyright	Copyright (c) 2024 - All Rights reserved.
--!
--! \note		Target devices : No specific target
--! \note		Tool versions  : No specific tool
--! \note		Dependencies   : No specific dependencies
--!
--! \ingroup	None
--! \warning	None
--!
--! \note		Revisions:
--!				- 1.0	22-07-2024	<urielcontardi@hotmail.com>
--!				First revision.
--------------------------------------------------------------------------
-- Default libraries
--------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

use std.textio.all;

--------------------------------------------------------------------------
-- User packages
--------------------------------------------------------------------------
use work.Solver_pkg.all;

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity StateSpaceSolver_tb is
End entity;

Architecture behavior of StateSpaceSolver_tb is

    --------------------------------------------------------------------------
    -- Clock definition
    --------------------------------------------------------------------------
    constant CLK_FREQUENCY  : integer   := 160e6;
    constant CLK_PERIOD     : time      := 1 sec / CLK_FREQUENCY;
    constant N_SS           : natural   := 5; -- Number of State Space
    constant N_IN           : natural   := 2; -- Inputs number of State Space

    --------------------------------------------------------------------------
    -- Factors
    --------------------------------------------------------------------------
    constant UVEC      : vector_fp_t(0 to N_IN - 1) := (
        x"00000002", x"00000003"
    );

    constant AMATRIX : matrix_fp_t(0 to N_SS - 1, 0 to N_SS - 1) := (
    (x"00000001", x"00000002", x"00000003", x"00000004", x"00000005"),
    (x"00000010", x"00000011", x"00000012", x"00000013", x"00000014"),
    (x"00000020", x"00000021", x"00000022", x"00000023", x"00000024"),
    (x"00000030", x"00000031", x"00000032", x"00000033", x"00000034"),
    (x"00000040", x"00000041", x"00000042", x"00000043", x"00000044") 
    );

    constant BMATRIX : matrix_fp_t(0 to N_SS - 1, 0 to N_IN - 1) := (
    (x"00000100", x"00000200"),
    (x"00001000", x"00001100"),
    (x"00002000", x"00002100"),
    (x"00003000", x"00003100"),
    (x"00004000", x"00004100") 
    );

    --------------------------------------------------------------------------
    -- UUT ports
    --------------------------------------------------------------------------
    signal sysclk       : std_logic := '0';
    signal start_i      : std_logic := '0';
    signal busy_o       : std_logic;
    signal UVec_i       : vector_fp_t(0 to N_IN - 1) := UVEC;
    signal AMatrix_i    : matrix_fp_t(0 to N_SS - 1, 0 to N_SS - 1) := AMATRIX;
    signal BMatrix_i    : matrix_fp_t(0 to N_SS - 1, 0 to N_IN - 1) := BMATRIX;
    signal XVec_o       : vector_fp_t(0 to N_SS - 1);

Begin
    
    --------------------------------------------------------------------------
    -- Clk generation
    --------------------------------------------------------------------------
    sysclk <= not sysclk after CLK_PERIOD/2;

    --------------------------------------------------------------------------
    -- UUT
    --------------------------------------------------------------------------
    uut: Entity work.StateSpaceSolver
    Generic map(
        N_SS    => N_SS, 
        N_IN    => N_IN
    )
    Port map(
        sysclk      => sysclk,
        start_i     => start_i,
        busy_o      => busy_o,
        UVec_i      => UVec_i,
        AMatrix_i   => AMatrix_i,
        BMatrix_i   => BMatrix_i,
        XVec_o      => XVec_o
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

    Begin
        

        wait for CLK_PERIOD * 5;
        wait until rising_edge(sysclk);
        wait for CLK_PERIOD * 50;

        --------------------------------------------------------------------------
        -- Stimulus
        --------------------------------------------------------------------------
        tickSignal(start_i);
        wait for CLK_PERIOD *100;

        report ".......................................... Tamanho de  BMatrix_i ..........................................";
        report "The row range is " & integer'image(BMatrix_i'range(1)'left) & " to " & integer'image(BMatrix_i'range(1)'right);
        report "The column range is " & integer'image(BMatrix_i'range(2)'left) & " to " & integer'image(BMatrix_i'range(2)'right);
        
    End process;

End architecture;
