--! \file		Top_HIL.vhd
--!
--! \brief		
--!
--! \author		Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       24-07-2025
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
--!				- 1.0	24-07-2025	<urielcontardi@hotmail.co>
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
use work.BilinearSolverPkg.all;

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity Top_HIL is
    Generic (
        CLK_FREQUENCY          : integer   := 200e6;
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
    -- TIM Parameters
    --------------------------------------------------------------------------
    constant DATA_WIDTH          : natural := 42;  -- Data width for fixed-point representation
    constant CLOCK_FREQUENCY     : natural := 200e6;        -- Clock frequency
    constant DISCRETIZATION_STEP : real    := 100.0e-9;     -- Discretization step
    constant param_rs            : real    := 0.0;          -- Stator resistance
    constant param_rr            : real    := 0.2826;       -- Rotor resistance
    constant param_ls            : real    := 3.1364e-3;    -- Stator inductance
    constant param_lr            : real    := 6.3264e-3;    -- Rotor inductance
    constant param_lm            : real    := 109.9442e-3;  -- Mutual inductance
    constant param_j             : real    := 0.192;        -- Moment of inertia
    constant param_poles         : real    := 2.0;           -- Number of poles

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
    sysclk <= clk_i;

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
    TIMSolver_Inst: Entity work.TIM_Solver
    Generic map(
        DATA_WIDTH          => DATA_WIDTH,          
        CLOCK_FREQUENCY     => CLOCK_FREQUENCY,     
        DISCRETIZATION_STEP => DISCRETIZATION_STEP, 
        param_rs            => param_rs,            
        param_rr            => param_rr,            
        param_ls            => param_ls,            
        param_lr            => param_lr,            
        param_lm            => param_lm,            
        param_j             => param_j,             
        param_poles         => param_poles
    )
    Port map(
        sysclk              : in std_logic;
        reset_n             : in std_logic;
        va_i                : in std_logic_vector(DATA_WIDTH-1 downto 0);
        vb_i                : in std_logic_vector(DATA_WIDTH-1 downto 0);
        vc_i                : in std_logic_vector(DATA_WIDTH-1 downto 0);
        torque_load_i       : in std_logic_vector(DATA_WIDTH-1 downto 0);
        ia_o                : out std_logic_vector(DATA_WIDTH-1 downto 0);
        ib_o                : out std_logic_vector(DATA_WIDTH-1 downto 0);
        ic_o                : out std_logic_vector(DATA_WIDTH-1 downto 0);
        flux_stator_alpha_o : out std_logic_vector(DATA_WIDTH-1 downto 0);
        flux_stator_beta_o  : out std_logic_vector(DATA_WIDTH-1 downto 0);
        torque_em_o         : out std_logic_vector(DATA_WIDTH-1 downto 0);
        speed_mech_o        : out std_logic_vector(DATA_WIDTH-1 downto 0);
        data_valid_o        : out std_logic;    -- Output data valid flag
        ready_o             : out std_logic     -- Ready for new inputs
    );

End Architecture;
