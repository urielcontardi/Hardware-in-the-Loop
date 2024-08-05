--! \file		Top_HIL.vhd
--!
--! \brief		
--!
--! \author		Uriel Abe Contardi (e-uriel@weg.net)
--! \date       16-04-2024
--!
--! \version    1.0
--!
--! \copyright	Copyright (c) 2022 WEG - All Rights reserved.
--!
--! \note		Target devices : No specific target
--! \note		Tool versions  : No specific tool
--! \note		Dependencies   : No specific dependencies
--!
--! \ingroup	WCW
--! \warning	None
--!
--! \note		Revisions:
--!				- 1.0	16-04-2024	<e-uriel@weg.net>
--!				First revision.
--------------------------------------------------------------------------
-- Default libraries
--------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

--------------------------------------------------------------------------
-- User packages
--------------------------------------------------------------------------
use work.Solver_pkg.all;

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity Top_HIL is
    Generic (
        CLK_FREQUENCY          : integer   := 160e6; -- PLL IP
        STATE_SPACE_FREQUENCY  : integer   := 10e6
    );
    Port (
        clk_i       : in std_logic;
        reset_n     : in std_logic;

        -- Inputs (Phases - NPC Switch)
        U_NPC_i    : in std_logic_vector(3 downto 0); -- S1, S2, S3, S4
        V_NPC_i    : in std_logic_vector(3 downto 0);
        W_NPC_i    : in std_logic_vector(3 downto 0)
        
    );
End entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
Architecture rtl of Top_HIL is

    --------------------------------------------------------------------------
    -- Constants
    --------------------------------------------------------------------------
    -- Phase
    constant N_PHASE                : integer := 3;
    constant U_PHASE                : integer := 0;
    constant V_PHASE                : integer := 1;
    constant W_PHASE                : integer := 2;

    -- VDC Value (750V)
    constant VDC_POS_VALUE          : fixed_point_data_t := x"02EE0000";
    constant VDC_NEG_VALUE          : fixed_point_data_t := x"FD120000";

    --------------------------------------------------------------------------
    -- LCL State Space Model
    --------------------------------------------------------------------------
    constant N_SS_LCL : integer := 5;
    constant N_IN_LCL : integer := 2;

    constant AMATRIX : matrix_fp_t(0 to N_SS - 1, 0 to N_SS - 1) := (
    (x"00010000", x"00000000", x"00000000", x"FFFFFED6", x"00000000"),
    (x"00000000", x"00010000", x"00000000", x"00000027", x"FFFFFFD9"),
    (x"00000000", x"00000000", x"00010000", x"00000000", x"00000000"),
    (x"000000DA", x"FFFFFF26", x"FFFFFF26", x"0000FFA9", x"00000057"),
    (x"00000000", x"0000051F", x"00000000", x"0000020C", x"0000FDF4")
    );

    constant BMATRIX : matrix_fp_t(0 to N_SS - 1, 0 to N_IN - 1) := (
    (x"0000012A", x"00000000"),
    (x"00000000", x"00000000"),
    (x"00000000", x"00000000"),
    (x"00000000", x"00000000"),
    (x"00000000", x"00000000")
    );

    --------------------------------------------------------------------------
    -- Signals
    --------------------------------------------------------------------------
    signal sysclk       : std_logic;
    signal sampleTick   : std_logic := '0';

    type XVec_phase_t is array (0 to N_PHASE - 1) of vector_fp_t(0 to N_SS - 1);
    type UVec_phase_t is array (0 to N_PHASE - 1) of vector_fp_t(0 to N_IN - 1);

    signal XVec         : XVec_phase_t;
    signal UVec         : UVec_phase_t;

Begin

    --------------------------------------------------------------------------
    -- PLL 
    --------------------------------------------------------------------------
    --PLL_Inst : work.HIL_PLL
    sysclk <= clk_i;

    --------------------------------------------------------------------------
    -- StateSpace Solver Sample Frequency
    --------------------------------------------------------------------------
    SampleFrequency : process (sysclk)
        constant SAMPLE_FREQ_CTR    : integer := CLK_FREQUENCY/STATE_SPACE_FREQUENCY;
        variable ctrSampleFreq      : integer := 0;
    begin
        if rising_edge(sysclk) then

            if ctrSampleFreq < SAMPLE_FREQ_CTR then
                ctrSampleFreq := ctrSampleFreq + 1;
                sampleTick <= '0';
            else
                sampleTick <= '1';
            end if;
            
        end if;
    end process;

    --------------------------------------------------------------------------
    -- State Space Input 
    --------------------------------------------------------------------------
    -- Inverter Voltage
    UVec(U_PHASE)(0) <= VDC_POS_VALUE when U_NPC_i = "0011" else
                        VDC_NEG_VALUE when U_NPC_i = "1100" else
                        (others => '0');

    UVec(V_PHASE)(0) <= VDC_POS_VALUE when V_NPC_i = "0011" else
                        VDC_NEG_VALUE when V_NPC_i = "1100" else
                        (others => '0');

    UVec(W_PHASE)(0) <= VDC_POS_VALUE when W_NPC_i = "0011" else
                        VDC_NEG_VALUE when W_NPC_i = "1100" else
                        (others => '0');

    -- Grid Voltage, in this case we are putting it in short
    UVec(U_PHASE)(1) <= (others => '0');
    UVec(V_PHASE)(1) <= (others => '0');
    UVec(W_PHASE)(1) <= (others => '0');
    
    --------------------------------------------------------------------------
    -- State Space Solver
    --------------------------------------------------------------------------
    StateSpacePhasesGen : for i in 0 to 2 generate
        StateSpaceSolver_Inst : Entity work.StateSpaceSolver
        Generic map(
            N_SS    => N_SS_LCL,
            N_IN    => N_IN_LCL
        )
        Port map(
            sysclk      => sysclk,
            -- Interface
            start_i     => sampleTick,
            busy_o      => open,
            -- Vector Inputs
            UVec_i      => UVec(i),
            -- Coefficients
            AMatrix_i   => AMATRIX,
            BMatrix_i   => BMATRIX,
            -- Vector Outputs 
            XVec_o      => XVec(i)
        ); 
    End generate;

End Architecture;
