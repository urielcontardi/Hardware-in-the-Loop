--! \file       Top_HIL_Zynq.vhd
--!
--! \brief      Top-level for EBAZ4205 (Zynq-7010)
--!
--!             ARCHITECTURE:
--!
--!             zynq_ps7_wrapper (Block Design)
--!               ├─ fclk_clk0 (100 MHz) ──────────────────────────┐
--!               ├─ fclk_reset_n ──────────────────────────────────┤
--!               ├─ va_ref[31:0]  ─────────────────────────────────┤ clk/rst
--!               ├─ vb_ref[31:0]  ─────────────────────────────────┤
--!               ├─ vc_ref[31:0]  ─────────────────────────────────┤
--!               └─ pwm_ctrl[31:0] ────────────────────────────────┤
--!                   bit 0 = pwm_enb                               │
--!                   bit 1 = clear                                 │
--!                                                                  │
--!             NPCManager ◄── va/vb/vc_ref (from PS via AXI GPIO)  │
--!               └─ pwm_a/b/c_o[3:0] ──────────────────── PORTS (DATA1)
--!
--!             NPC→Voltage (combinational)
--!
--!             TIM_Solver ◄── va/vb/vc_motor, torque
--!               └─ ialpha/ibeta/flux/speed ──► SerialManager
--!
--!             SerialManager ◄──► UART (J7: F19/F20) ◄──► App
--!
--!             PS (ARM Cortex-A9) runs V/F ramp algorithm in C and
--!             writes va_ref/vb_ref/vc_ref to PL via AXI GPIO.
--!
--! \author     Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       28-03-2026

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.BilinearSolverPkg.all;

entity Top_HIL_Zynq is
    Generic (
        -- NPC Modulator
        PWM_FREQUENCY       : natural := 20_000;
        NPC_DATA_WIDTH      : natural := 32;
        MIN_PULSE_WIDTH     : natural := 50;       -- scaled for 100 MHz
        DEAD_TIME           : natural := 25;       -- scaled for 100 MHz

        -- TIM Solver
        TIM_DATA_WIDTH      : natural := 42;
        DISCRETIZATION_STEP : real    := 100.0e-9;

        -- Motor parameters
        MOTOR_RS            : real    := 0.435;
        MOTOR_RR            : real    := 0.2826;
        MOTOR_LS            : real    := 3.1364e-3;
        MOTOR_LR            : real    := 6.3264e-3;
        MOTOR_LM            : real    := 109.9442e-3;
        MOTOR_J             : real    := 0.192;
        MOTOR_NPP           : real    := 2.0;

        -- UART
        BAUD_RATE           : natural := 115200
    );
    Port (
        -- ── PS7 DDR / FIXED_IO (required for Zynq PS) ──────────────────────
        DDR_addr            : inout std_logic_vector(14 downto 0);
        DDR_ba              : inout std_logic_vector(2 downto 0);
        DDR_cas_n           : inout std_logic;
        DDR_ck_n            : inout std_logic;
        DDR_ck_p            : inout std_logic;
        DDR_cke             : inout std_logic;
        DDR_cs_n            : inout std_logic;
        DDR_dm              : inout std_logic_vector(3 downto 0);
        DDR_dq              : inout std_logic_vector(31 downto 0);
        DDR_dqs_n           : inout std_logic_vector(3 downto 0);
        DDR_dqs_p           : inout std_logic_vector(3 downto 0);
        DDR_odt             : inout std_logic;
        DDR_ras_n           : inout std_logic;
        DDR_reset_n         : inout std_logic;
        DDR_we_n            : inout std_logic;
        FIXED_IO_ddr_vrn    : inout std_logic;
        FIXED_IO_ddr_vrp    : inout std_logic;
        FIXED_IO_mio        : inout std_logic_vector(53 downto 0);
        FIXED_IO_ps_clk     : inout std_logic;
        FIXED_IO_ps_porb    : inout std_logic;
        FIXED_IO_ps_srstb   : inout std_logic;

        -- ── Gate outputs → DATA1 connector ─────────────────────────────────
        pwm_a_o             : out std_logic_vector(3 downto 0);
        pwm_b_o             : out std_logic_vector(3 downto 0);
        pwm_c_o             : out std_logic_vector(3 downto 0);

        -- ── UART → J7 header (F19/F20) ──────────────────────────────────────
        uart_rx_i           : in  std_logic;
        uart_tx_o           : out std_logic;

        -- ── Status LEDs ──────────────────────────────────────────────────────
        led_green_o         : out std_logic;   -- PWM running
        led_red_o           : out std_logic    -- Fault
    );
end entity;

architecture rtl of Top_HIL_Zynq is

    -- ── Constants ─────────────────────────────────────────────────────────────
    constant CLK_FREQUENCY   : natural := 100_000_000;  -- PS FCLK0 = 100 MHz

    constant NPC_STATE_POS   : std_logic_vector(3 downto 0) := "0011";
    constant NPC_STATE_NEG   : std_logic_vector(3 downto 0) := "1100";

    -- ── Internal signals ──────────────────────────────────────────────────────
    signal fclk              : std_logic;
    signal reset_n           : std_logic;

    -- PS → NPC (via AXI GPIO in BD)
    signal va_ref            : std_logic_vector(NPC_DATA_WIDTH-1 downto 0);
    signal vb_ref            : std_logic_vector(NPC_DATA_WIDTH-1 downto 0);
    signal vc_ref            : std_logic_vector(NPC_DATA_WIDTH-1 downto 0);
    signal pwm_ctrl          : std_logic_vector(31 downto 0);

    -- NPC gate states
    signal pwm_a_int         : std_logic_vector(3 downto 0);
    signal pwm_b_int         : std_logic_vector(3 downto 0);
    signal pwm_c_int         : std_logic_vector(3 downto 0);
    signal pwm_on_int        : std_logic;
    signal pwm_fault_int     : std_logic;
    signal carrier_tick_int  : std_logic;

    -- NPC → motor voltages
    signal va_motor          : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal vb_motor          : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal vc_motor          : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);

    -- DC bus levels (from SerialManager config)
    signal vdc_bus           : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal vdc_pos           : signed(TIM_DATA_WIDTH-1 downto 0);
    signal vdc_neg           : signed(TIM_DATA_WIDTH-1 downto 0);

    -- SerialManager config
    signal torque_load       : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal config_valid      : std_logic;

    -- TIM Solver outputs
    signal ialpha_int        : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal ibeta_int         : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal flux_alpha_int    : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal flux_beta_int     : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal speed_mech_int    : std_logic_vector(TIM_DATA_WIDTH-1 downto 0);
    signal data_valid_int    : std_logic;

begin

    -- ── PS7 Block Design Wrapper ───────────────────────────────────────────────
    PS7_Inst : entity work.zynq_ps7_wrapper
    port map (
        DDR_addr         => DDR_addr,
        DDR_ba           => DDR_ba,
        DDR_cas_n        => DDR_cas_n,
        DDR_ck_n         => DDR_ck_n,
        DDR_ck_p         => DDR_ck_p,
        DDR_cke          => DDR_cke,
        DDR_cs_n         => DDR_cs_n,
        DDR_dm           => DDR_dm,
        DDR_dq           => DDR_dq,
        DDR_dqs_n        => DDR_dqs_n,
        DDR_dqs_p        => DDR_dqs_p,
        DDR_odt          => DDR_odt,
        DDR_ras_n        => DDR_ras_n,
        DDR_reset_n      => DDR_reset_n,
        DDR_we_n         => DDR_we_n,
        FIXED_IO_ddr_vrn => FIXED_IO_ddr_vrn,
        FIXED_IO_ddr_vrp => FIXED_IO_ddr_vrp,
        FIXED_IO_mio     => FIXED_IO_mio,
        FIXED_IO_ps_clk  => FIXED_IO_ps_clk,
        FIXED_IO_ps_porb => FIXED_IO_ps_porb,
        FIXED_IO_ps_srstb=> FIXED_IO_ps_srstb,
        fclk_clk0        => fclk,
        fclk_reset_n     => reset_n,
        va_ref           => va_ref,
        vb_ref           => vb_ref,
        vc_ref           => vc_ref,
        pwm_ctrl         => pwm_ctrl
    );

    -- ── NPC Manager (PWM Modulator + Gate Drivers) ─────────────────────────────
    -- va_ref/vb_ref/vc_ref written by PS (ARM) via AXI GPIO (0x41200000/0x41210000)
    -- pwm_ctrl bit[0] = enable, bit[1] = clear
    NPCMgr_Inst : entity work.NPCManager
    generic map (
        CLK_FREQ        => CLK_FREQUENCY,
        PWM_FREQ        => PWM_FREQUENCY,
        DATA_WIDTH      => NPC_DATA_WIDTH,
        LOAD_BOTH_EDGES => false,
        OUTPUT_REG      => true,
        MIN_PULSE_WIDTH => MIN_PULSE_WIDTH,
        DEAD_TIME       => DEAD_TIME,
        WAIT_STATE_CNT  => CLK_FREQUENCY / 1000,
        INVERTED_PWM    => false
    )
    port map (
        sysclk         => fclk,
        reset_n        => reset_n,
        pwm_enb_i      => pwm_ctrl(0),
        clear_i        => pwm_ctrl(1),
        va_ref_i       => va_ref,
        vb_ref_i       => vb_ref,
        vc_ref_i       => vc_ref,
        carrier_tick_o => carrier_tick_int,
        sample_tick_o  => open,
        pwm_a_o        => pwm_a_int,
        pwm_b_o        => pwm_b_int,
        pwm_c_o        => pwm_c_int,
        pwm_on_o       => pwm_on_int,
        fault_o        => pwm_fault_int,
        fs_fault_o     => open,
        minw_fault_o   => open
    );

    pwm_a_o    <= pwm_a_int;
    pwm_b_o    <= pwm_b_int;
    pwm_c_o    <= pwm_c_int;
    led_green_o <= pwm_on_int;
    led_red_o   <= pwm_fault_int;

    -- ── NPC State → Motor Voltage (combinational) ─────────────────────────────
    vdc_pos <= shift_right(signed(vdc_bus), 1);
    vdc_neg <= -shift_right(signed(vdc_bus), 1);

    NPC_to_Voltage : process(pwm_a_int, pwm_b_int, pwm_c_int, vdc_pos, vdc_neg)
    begin
        case pwm_a_int is
            when NPC_STATE_POS => va_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_NEG => va_motor <= std_logic_vector(vdc_neg);
            when others        => va_motor <= (others => '0');
        end case;
        case pwm_b_int is
            when NPC_STATE_POS => vb_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_NEG => vb_motor <= std_logic_vector(vdc_neg);
            when others        => vb_motor <= (others => '0');
        end case;
        case pwm_c_int is
            when NPC_STATE_POS => vc_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_NEG => vc_motor <= std_logic_vector(vdc_neg);
            when others        => vc_motor <= (others => '0');
        end case;
    end process;

    -- ── TIM Solver (Motor Model) ───────────────────────────────────────────────
    TIM_Inst : entity work.TIM_Solver
    generic map (
        DATA_WIDTH      => TIM_DATA_WIDTH,
        CLOCK_FREQUENCY => CLK_FREQUENCY,
        Ts              => DISCRETIZATION_STEP,
        rs              => MOTOR_RS,
        rr              => MOTOR_RR,
        ls              => MOTOR_LS,
        lr              => MOTOR_LR,
        lm              => MOTOR_LM,
        j               => MOTOR_J,
        npp             => MOTOR_NPP
    )
    port map (
        sysclk             => fclk,
        reset_n            => reset_n,
        va_i               => va_motor,
        vb_i               => vb_motor,
        vc_i               => vc_motor,
        torque_load_i      => torque_load,
        ialpha_o           => ialpha_int,
        ibeta_o            => ibeta_int,
        flux_rotor_alpha_o => flux_alpha_int,
        flux_rotor_beta_o  => flux_beta_int,
        speed_mech_o       => speed_mech_int,
        data_valid_o       => data_valid_int
    );

    -- ── Serial Manager (UART ↔ App) ────────────────────────────────────────────
    -- App protocol (SerialManager): 115200 baud, 8N1
    --   Write reg : 'W' | ADDR(1B) | DATA(6B MSB-first)
    --   Read reg  : 'R' | ADDR(1B)
    --   Read all  : 'A'
    -- Registers:
    --   0x00 W  vdc_bus     (Q14.28, 42-bit)
    --   0x01 W  torque_load (Q14.28, 42-bit)
    --   0x02 R  va_motor
    --   0x03 R  vb_motor
    --   0x04 R  vc_motor
    --   0x05 R  ialpha
    --   0x06 R  ibeta
    --   0x07 R  flux_alpha
    --   0x08 R  flux_beta
    --   0x09 R  speed_mech
    SerMgr_Inst : entity work.SerialManager
    generic map (
        CLK_FREQ   => CLK_FREQUENCY,
        BAUD_RATE  => BAUD_RATE,
        DATA_WIDTH => TIM_DATA_WIDTH
    )
    port map (
        clk_i          => fclk,
        reset_n_i      => reset_n,
        rx_i           => uart_rx_i,
        tx_o           => uart_tx_o,
        vdc_bus_o      => vdc_bus,
        torque_load_o  => torque_load,
        config_valid_o => config_valid,
        va_motor_i     => va_motor,
        vb_motor_i     => vb_motor,
        vc_motor_i     => vc_motor,
        ialpha_i       => ialpha_int,
        ibeta_i        => ibeta_int,
        flux_alpha_i   => flux_alpha_int,
        flux_beta_i    => flux_beta_int,
        speed_mech_i   => speed_mech_int,
        data_valid_i   => data_valid_int
    );

end architecture;
