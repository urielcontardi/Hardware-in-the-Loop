--! \file		Top_HIL_tb.vhd
--!
--! \brief		
--!
--! \author		Uriel Abe Contardi (contardii@weg.net)
--! \date       04-08-2024
--!
--! \version    1.0
--!
--! \copyright	Copyright (c) 2024 WEG - All Rights reserved.
--!
--! \note		Target devices : No specific target
--! \note		Tool versions  : No specific tool
--! \note		Dependencies   : No specific dependencies
--!
--! \ingroup	None
--! \warning	None
--!
--! \note		Revisions:
--!				- 1.0	04-08-2024	<contardii@weg.net>
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

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity Top_HIL_tb is
End entity;

Architecture behavior of Top_HIL_tb is

    --------------------------------------------------------------------------
    -- Clock definition
    --------------------------------------------------------------------------
    constant CLK_FREQUENCY  : integer   := 160e6;
    constant CLK_PERIOD     : time      := 1 sec / CLK_FREQUENCY;

    --------------------------------------------------------------------------
    -- PWM text File
    --------------------------------------------------------------------------
    constant N_COLUMN   : integer   := 0;
    type READ_BUFFER_TYPE is array(N_COLUMN - 1 downto 0) of std_logic;
    constant TXT_FILE   : string    := "/home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/extras/Simulation/NPC_PWM.txt";
    constant FILE_SAMPLE_FREQ   : integer   := 100e3;
    constant FILE_SAMPLE_PERIOD : time      := 1 sec / FILE_SAMPLE_FREQ;

    --------------------------------------------------------------------------
    -- UUT ports
    --------------------------------------------------------------------------
    constant STATE_SPACE_FREQUENCY  : integer := 10e6;

    signal clk_i    : std_logic := '0';
    signal reset_n  : std_logic := '0';
    signal U_NPC_i  : std_logic_vector(3 downto 0);
    signal V_NPC_i  : std_logic_vector(3 downto 0);
    signal W_NPC_i  : std_logic_vector(3 downto 0);

Begin

    --------------------------------------------------------------------------
    -- Clk generation
    --------------------------------------------------------------------------
    sysclk <= not sysclk after CLK_PERIOD/2;

    --------------------------------------------------------------------------
    -- UUT
    --------------------------------------------------------------------------
    UUT : Entity work.Top_HIL
    Generic map(
        CLK_FREQUENCY          => CLK_FREQUENCY,
        STATE_SPACE_FREQUENCY  => STATE_SPACE_FREQUENCY
    )
    Port map(
        clk_i       => clk_i,
        reset_n     => reset_n,
        -- Inputs (Phases - NPC Switch)
        U_NPC_i    => U_NPC_i,
        V_NPC_i    => V_NPC_i,
        W_NPC_i    => W_NPC_i
    );

    --------------------------------------------------------------------------
    -- Load PWM 
    --------------------------------------------------------------------------
    FileRead_Inverter_PWM_Width : process
        variable fileLine   : line;
        variable readBuffer : READ_BUFFER_TYPE;
        file fileName       : text is in TXT_FILE;
    begin

        while true loop

            -- Verify file end
            if endfile(fileName) then
                file_close(fileName);
                file_open(fileName, MEASURES_FILE, read_mode);
            end if;

            -- Read Line
            readline (fileName, fileLine);
            for i in 0 to N_COLUMN - 1 loop
                read(fileLine, readBuffer(i));
            end loop;

            -- Fill Array
            for aa in U_NPC_i'range loop
                U_NPC_i(aa) <= std_logic(readBuffer(aa));
                V_NPC_i(aa) <= std_logic(readBuffer(aa));
                W_NPC_i(aa) <= std_logic(readBuffer(aa));
            end loop;

            -- Wait Sample Period
            wait for FILE_SAMPLE_PERIOD;

        end loop;

    end process;


End architecture;
