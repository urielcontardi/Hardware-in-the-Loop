--! \file		MIT.vhd
--!
--! \brief		Motor de Indução Trifásico (MIT) - Emulador Hardware-in-the-Loop
--!             Este módulo implementa um modelo matemático de motor de indução
--!             trifásico em tempo real para simulação HIL.
--!
--!             ENTRADAS:
--!             - Tensões trifásicas (Va, Vb, Vc)
--!             - Torque de carga mecânica
--!             - Parâmetros do motor (Rs, Rr, Ls, Lr, Lm, J, B, polos)
--!
--!             SAÍDAS:
--!             - Correntes trifásicas (Ia, Ib, Ic)
--!             - Fluxos do rotor e estator (componentes dq)
--!             - Torque eletromagnético
--!             - Velocidade mecânica e elétrica
--!             - Posição do rotor
--!
--! \author		Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       31-07-2025
--!
--! \version    1.0
--!
--! \copyright	Copyright (c) 2025 - All Rights reserved.
--!
--! \note		Target devices : Xilinx FPGA
--! \note		Tool versions  : Vivado 2023.x
--! \note		Dependencies   : Multiplicadores e somadores IP cores
--!
--! \ingroup	HIL_Motors
--! \warning	Usar aritmética de ponto fixo para precisão adequada
--!
--! \note		Revisions:
--!				- 1.0	31-07-2025	<urielcontardi@hotmail.com>
--!				Primeira revisão com interface completa do MIT.
--------------------------------------------------------------------------
-- Default libraries
--------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

--------------------------------------------------------------------------
-- User packages
--------------------------------------------------------------------------

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity MIT is
    Generic (
        -- Motor parameters
        param_rs        : real := 0.0;          -- Stator resistance
        param_rr        : real := 0.2826;       -- Rotor resistance
        param_ls        : real := 3.1364e-3;    -- Stator inductance
        param_lr        : real := 6.3264e-3;    -- Rotor inductance
        param_lm        : real := 109.9442e-3;  -- Mutual inductance
        param_j         : real := 0.192;        -- Moment of inertia
        param_poles     : real := 2.0           -- Number of poles
    );
    Port (
        -- Clock and reset
        sysclk          : in std_logic;
        reset_n         : in std_logic;
        
        -- Control signals
        enable_i        : in std_logic;
        
        -- Input voltages (3-phase ABC)
        va_i            : in std_logic_vector(DATA_WIDTH-1 downto 0);
        vb_i            : in std_logic_vector(DATA_WIDTH-1 downto 0);
        vc_i            : in std_logic_vector(DATA_WIDTH-1 downto 0);
        
        -- Mechanical load torque input
        torque_load_i   : in std_logic_vector(DATA_WIDTH-1 downto 0);
        
        -- Output currents (3-phase ABC)
        ia_o            : out std_logic_vector(DATA_WIDTH-1 downto 0);
        ib_o            : out std_logic_vector(DATA_WIDTH-1 downto 0);
        ic_o            : out std_logic_vector(DATA_WIDTH-1 downto 0);
        
        -- Rotor fluxes (alpha-beta components)
        flux_rotor_alpha_o  : out std_logic_vector(DATA_WIDTH-1 downto 0);
        flux_rotor_beta_o   : out std_logic_vector(DATA_WIDTH-1 downto 0);
        
        -- Stator fluxes (alpha-beta components)
        flux_stator_alpha_o : out std_logic_vector(DATA_WIDTH-1 downto 0);
        flux_stator_beta_o  : out std_logic_vector(DATA_WIDTH-1 downto 0);
        
        -- Electromagnetic torque
        torque_em_o         : out std_logic_vector(DATA_WIDTH-1 downto 0);
        
        -- Mechanical outputs
        speed_mech_o        : out std_logic_vector(DATA_WIDTH-1 downto 0);  -- Mechanical speed (rad/s)
        speed_elec_o        : out std_logic_vector(DATA_WIDTH-1 downto 0);  -- Electrical speed (rad/s)
        position_o          : out std_logic_vector(DATA_WIDTH-1 downto 0);  -- Rotor position (rad)
        
        -- Status and control
        data_valid_o        : out std_logic;    -- Output data valid flag
        ready_o             : out std_logic;    -- Ready for new inputs
        error_o             : out std_logic     -- Error flag
    );
End entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
Architecture rtl of MIT is

    -- Internal signals for state variables
    signal rotor_flux_d_int     : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal rotor_flux_q_int     : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal stator_current_d_int : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal stator_current_q_int : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal rotor_speed_int      : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal rotor_position_int   : std_logic_vector(DATA_WIDTH-1 downto 0);
    
    -- Internal signals for transformations
    signal voltage_d            : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal voltage_q            : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal current_d            : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal current_q            : std_logic_vector(DATA_WIDTH-1 downto 0);
    
    -- Control signals
    signal calculation_enable   : std_logic;
    signal state_update_enable  : std_logic;
    signal transform_enable     : std_logic;
    
    -- Status signals
    signal ready_int            : std_logic;
    signal data_valid_int       : std_logic;
    signal error_int            : std_logic;

Begin

    --------------------------------------------------------------------------
    -- Clarke Transformation
    --------------------------------------------------------------------------


    --------------------------------------------------------------------------
    -- Solver Unit
    --------------------------------------------------------------------------


End architecture;
