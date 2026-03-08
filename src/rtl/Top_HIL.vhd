--! \file       Top_HIL.vhd
--!
--! \brief      Top-level Hardware-in-the-Loop (HIL) module
--!             Integrates NPC Modulator with Three-Phase Induction Motor (TIM) Solver
--!             for real-time power electronics and motor simulation.
--!
--!             ARCHITECTURE OVERVIEW:
--!             ┌─────────────────────────────────────────────────────────────────────┐
--!             │                          Top_HIL                                    │
--!             │                                                                     │
--!             │  ┌──────────────┐   PWM    ┌─────────────┐   V_abc   ┌───────────┐ │
--!             │  │  NPCManager  ├─────────►│ NPC→Voltage ├──────────►│TIM_Solver │ │
--!             │  │  (Modulator  │  States  │  Converter  │           │ (Motor    │ │
--!             │  │  + GateDrv)  │          └─────────────┘           │  Model)   │ │
--!             │  └──────▲───────┘                                    └─────┬─────┘ │
--!             │         │                                                  │       │
--!             │         │ Va,Vb,Vc_ref                           I_alpha,beta     │
--!             │         │ (from external)                        Flux, Speed       │
--!             │  ┌──────┴───────┐                                      │          │
--!             │  │   Config     │◄──────── (Future: Comm Module) ──────┘          │
--!             │  │   Registers  │                                                  │
--!             │  └──────────────┘                                                  │
--!             └─────────────────────────────────────────────────────────────────────┘
--!
--!             CONFIGURABLE PARAMETERS (via future communication module):
--!             - Voltage references (Va, Vb, Vc) - sinusoidal inputs from external
--!             - DC bus voltage (Vdc) - amplitude configuration
--!             - PWM enable/disable
--!             - Motor load torque
--!             - Motor parameters (optional runtime update)
--!
--! \author     Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       08-02-2026
--!
--! \version    2.0
--!
--! \copyright  Copyright (c) 2026 - All Rights reserved.
--!
--! \note       Target devices : Xilinx 7-series, UltraScale
--! \note       Tool versions  : Vivado 2020.2+
--! \note       Dependencies   : BilinearSolverPkg, NPCManager, TIM_Solver, SerialManager
--!
--! \note       Revisions:
--!             - 1.0  24-07-2025  First revision.
--!             - 2.0  08-02-2026  Integration of NPCManager + TIM_Solver

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
        -- Clock configuration
        CLK_FREQUENCY       : natural := 200_000_000;   -- System clock frequency (Hz)
        
        -- NPC Modulator parameters
        PWM_FREQUENCY       : natural := 20_000;        -- PWM switching frequency (Hz)
        NPC_DATA_WIDTH      : natural := 32;            -- Reference signal bit width
        MIN_PULSE_WIDTH     : natural := 100;           -- Minimum pulse width (clock cycles)
        DEAD_TIME           : natural := 50;            -- Dead time (clock cycles)
        
        -- TIM Solver parameters
        TIM_DATA_WIDTH      : natural := 42;            -- Fixed-point width for motor model
        DISCRETIZATION_STEP : real    := 100.0e-9;      -- Motor model discretization step (s)
        
        -- Motor parameters (default values - can be overridden)
        MOTOR_RS            : real    := 0.0;           -- Stator resistance (Ohm)
        MOTOR_RR            : real    := 0.2826;        -- Rotor resistance (Ohm)
        MOTOR_LS            : real    := 3.1364e-3;     -- Stator inductance (H)
        MOTOR_LR            : real    := 6.3264e-3;     -- Rotor inductance (H)
        MOTOR_LM            : real    := 109.9442e-3;   -- Mutual inductance (H)
        MOTOR_J             : real    := 0.192;         -- Moment of inertia (kg.m²)
        MOTOR_NPP           : real    := 2.0;           -- Number of pole pairs

        -- UART configuration
        BAUD_RATE           : natural := 115200          -- UART baud rate (bps)
    );
    Port (
        --------------------------------------------------------------------------
        -- System interface
        --------------------------------------------------------------------------
        clk_i               : in  std_logic;            -- System clock
        reset_n             : in  std_logic;            -- Active-low reset

        --------------------------------------------------------------------------
        -- NPC Modulator Control (from external/communication module)
        --------------------------------------------------------------------------
        pwm_enb_i           : in  std_logic;            -- PWM enable
        pwm_clear_i         : in  std_logic;            -- Clear PWM faults

        --! Voltage references (signed fixed-point, normalized to ±1.0)
        --! These should come from an external sine generator or communication module
        va_ref_i            : in  std_logic_vector(NPC_DATA_WIDTH-1 downto 0);
        vb_ref_i            : in  std_logic_vector(NPC_DATA_WIDTH-1 downto 0);
        vc_ref_i            : in  std_logic_vector(NPC_DATA_WIDTH-1 downto 0);

        --------------------------------------------------------------------------
        -- NPC Modulator Status Outputs
        --------------------------------------------------------------------------
        carrier_tick_o      : out std_logic;            -- Carrier period start
        sample_tick_o       : out std_logic;            -- Reference sample tick
        pwm_on_o            : out std_logic;            -- PWM is active
        pwm_fault_o         : out std_logic;            -- PWM fault detected

        --! Gate outputs per phase (directly to inverter or for monitoring)
        pwm_a_o             : out std_logic_vector(3 downto 0);
        pwm_b_o             : out std_logic_vector(3 downto 0);
        pwm_c_o             : out std_logic_vector(3 downto 0);

        --------------------------------------------------------------------------
        -- UART Interface (for configuration via serial)
        --------------------------------------------------------------------------
        uart_rx_i           : in  std_logic;            -- UART RX input
        uart_tx_o           : out std_logic             -- UART TX output

    );
End entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
Architecture rtl of Top_HIL is

    --------------------------------------------------------------------------
    -- Constants
    --------------------------------------------------------------------------
    -- NPC State encodings (from gate driver output)
    constant NPC_STATE_POS      : std_logic_vector(3 downto 0) := "0011";  -- +Vdc/2
    constant NPC_STATE_ZERO     : std_logic_vector(3 downto 0) := "0110";  -- 0
    constant NPC_STATE_NEG      : std_logic_vector(3 downto 0) := "1100";  -- -Vdc/2
    constant NPC_STATE_OFF      : std_logic_vector(3 downto 0) := "0000";  -- OFF

    --------------------------------------------------------------------------
    -- Internal Signals
    --------------------------------------------------------------------------
    -- System clock (through PLL if needed)
    signal sysclk               : std_logic;

    -- NPC Manager outputs (gate states)
    signal pwm_a_int            : std_logic_vector(3 downto 0);
    signal pwm_b_int            : std_logic_vector(3 downto 0);
    signal pwm_c_int            : std_logic_vector(3 downto 0);
    signal carrier_tick_int     : std_logic;

    -- Voltage conversion: NPC states → actual voltage levels
    signal va_motor             : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal vb_motor             : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal vc_motor             : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);

    -- DC bus voltage levels (calculated from vdc_bus_i)
    signal vdc_pos              : signed(TIM_DATA_WIDTH-1 downto 0);  -- +Vdc/2
    signal vdc_neg              : signed(TIM_DATA_WIDTH-1 downto 0);  -- -Vdc/2

    -- Fault signals
    signal fs_fault_int         : std_logic;
    signal minw_fault_int       : std_logic;

    -- Configuration from SerialManager
    signal vdc_bus              : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal torque_load          : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal config_valid         : std_logic;

    -- TIM Solver intermediate outputs (shared with SerialManager monitor)
    signal ialpha_int           : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal ibeta_int            : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal flux_rotor_alpha_int : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal flux_rotor_beta_int  : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal speed_mech_int       : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal data_valid_int       : std_logic;

Begin

    --------------------------------------------------------------------------
    -- Clock Assignment (placeholder for PLL if needed)
    --------------------------------------------------------------------------
    sysclk <= clk_i;

    --------------------------------------------------------------------------
    -- Serial Manager (UART-based config & monitoring)
    --------------------------------------------------------------------------
    SerialManager_Inst : entity work.SerialManager
    generic map (
        CLK_FREQ   => CLK_FREQUENCY,
        BAUD_RATE  => BAUD_RATE,
        DATA_WIDTH => TIM_DATA_WIDTH
    )
    port map (
        clk_i           => sysclk,
        reset_n_i       => reset_n,
        -- UART
        rx_i            => uart_rx_i,
        tx_o            => uart_tx_o,
        -- Config outputs
        vdc_bus_o       => vdc_bus,
        torque_load_o   => torque_load,
        config_valid_o  => config_valid,
        -- Monitor inputs
        va_motor_i      => va_motor,
        vb_motor_i      => vb_motor,
        vc_motor_i      => vc_motor,
        ialpha_i        => ialpha_int,
        ibeta_i         => ibeta_int,
        flux_alpha_i    => flux_rotor_alpha_int,
        flux_beta_i     => flux_rotor_beta_int,
        speed_mech_i    => speed_mech_int,
        data_valid_i    => data_valid_int
    );

    --------------------------------------------------------------------------
    -- DC Bus Voltage Calculation
    -- Vdc_pos = +Vdc/2, Vdc_neg = -Vdc/2
    --------------------------------------------------------------------------
    vdc_pos <= shift_right(signed(vdc_bus), 1);
    vdc_neg <= -shift_right(signed(vdc_bus), 1);

    --------------------------------------------------------------------------
    -- NPC Manager Instance (Modulator + Gate Drivers)
    --------------------------------------------------------------------------
    NPCManager_Inst : entity work.NPCManager
    generic map (
        CLK_FREQ         => CLK_FREQUENCY,
        PWM_FREQ         => PWM_FREQUENCY,
        DATA_WIDTH       => NPC_DATA_WIDTH,
        LOAD_BOTH_EDGES  => false,
        OUTPUT_REG       => true,
        MIN_PULSE_WIDTH  => MIN_PULSE_WIDTH,
        DEAD_TIME        => DEAD_TIME,
        WAIT_STATE_CNT   => CLK_FREQUENCY / 1000,  -- ~1ms wait state
        INVERTED_PWM     => false
    )
    port map (
        sysclk          => sysclk,
        reset_n         => reset_n,
        -- Control
        pwm_enb_i       => pwm_enb_i,
        clear_i         => pwm_clear_i,
        -- Voltage references (from external)
        va_ref_i        => va_ref_i,
        vb_ref_i        => vb_ref_i,
        vc_ref_i        => vc_ref_i,
        -- Sync outputs
        carrier_tick_o  => carrier_tick_int,
        sample_tick_o   => sample_tick_o,
        -- Gate outputs
        pwm_a_o         => pwm_a_int,
        pwm_b_o         => pwm_b_int,
        pwm_c_o         => pwm_c_int,
        -- Status
        pwm_on_o        => pwm_on_o,
        fault_o         => pwm_fault_o,
        fs_fault_o      => fs_fault_int,
        minw_fault_o    => minw_fault_int
    );

    -- Output assignments
    carrier_tick_o <= carrier_tick_int;
    pwm_a_o        <= pwm_a_int;
    pwm_b_o        <= pwm_b_int;
    pwm_c_o        <= pwm_c_int;

    --------------------------------------------------------------------------
    -- NPC State to Voltage Conversion
    -- Converts 4-bit gate states to actual voltage levels for motor model
    --------------------------------------------------------------------------
    NPC_to_Voltage : process(pwm_a_int, pwm_b_int, pwm_c_int, vdc_pos, vdc_neg)
    begin
        -- Phase A
        case pwm_a_int is
            when NPC_STATE_POS  => va_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_NEG  => va_motor <= std_logic_vector(vdc_neg);
            when others         => va_motor <= (others => '0');  -- ZERO or OFF
        end case;

        -- Phase B
        case pwm_b_int is
            when NPC_STATE_POS  => vb_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_NEG  => vb_motor <= std_logic_vector(vdc_neg);
            when others         => vb_motor <= (others => '0');
        end case;

        -- Phase C
        case pwm_c_int is
            when NPC_STATE_POS  => vc_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_NEG  => vc_motor <= std_logic_vector(vdc_neg);
            when others         => vc_motor <= (others => '0');
        end case;
    end process;

    --------------------------------------------------------------------------
    -- TIM Solver Instance (Three-Phase Induction Motor Model)
    --------------------------------------------------------------------------
    TIM_Solver_Inst : entity work.TIM_Solver
    generic map (
        DATA_WIDTH       => TIM_DATA_WIDTH,
        CLOCK_FREQUENCY  => CLK_FREQUENCY,
        Ts               => DISCRETIZATION_STEP,
        rs               => MOTOR_RS,
        rr               => MOTOR_RR,
        ls               => MOTOR_LS,
        lr               => MOTOR_LR,
        lm               => MOTOR_LM,
        j                => MOTOR_J,
        npp              => MOTOR_NPP
    )
    port map (
        sysclk              => sysclk,
        reset_n             => reset_n,
        -- Input voltages (from NPC converter)
        va_i                => va_motor,
        vb_i                => vb_motor,
        vc_i                => vc_motor,
        -- Mechanical load
        torque_load_i       => torque_load,
        -- Output currents (alpha-beta)
        ialpha_o            => ialpha_int,
        ibeta_o             => ibeta_int,
        -- Rotor fluxes
        flux_rotor_alpha_o  => flux_rotor_alpha_int,
        flux_rotor_beta_o   => flux_rotor_beta_int,
        -- Mechanical speed
        speed_mech_o        => speed_mech_int,
        -- Data valid
        data_valid_o        => data_valid_int
    );

End Architecture;
