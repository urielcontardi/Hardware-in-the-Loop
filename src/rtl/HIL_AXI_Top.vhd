--! \file       HIL_AXI_Top.vhd
--!
--! \brief      HIL AXI Top — Wrapper PS-controlado para simulação de motor
--!
--!             O PS calcula as referências de tensão (V/F, FOC ou qualquer
--!             algoritmo) e as escreve via HIL_Regs_AXI a cada período de portadora.
--!             O PL gera a interrupção (carrier_tick_o → IRQ_F2P), faz a
--!             modulação NPC, converte estados → tensão e roda o TIM_Solver.
--!
--!             FLUXO:
--!               NPCModulator (portadora 1 kHz)
--!                   │ carrier_tick_o ──────────────► IRQ_F2P → PS
--!                   │                                   │ escreve va/vb/vc
--!                   ▼ sample no valley                  ▼
--!               NPCManager (gate states)         HIL_Regs_AXI refs
--!                   │
--!               NPC_to_Voltage (±Vdc/2)
--!                   │
--!               TIM_Solver
--!                   │
--!               AXI4-Stream → AXI DMA → DDR
--!
--! MAPA DE REGISTRADORES HIL_Regs_AXI (escritas do PS):
--!   0x00 va_ref, 0x04 vb_ref, 0x08 vc_ref
--!   0x0C pwm_ctrl, 0x10 vdc_word, 0x14 torque_word
--!
--! SAÍDA AXI4-STREAM (256 bits, 1 beat por amostra):
--!   bits[ 41: 0]  = ialpha
--!   bits[ 83:42]  = ibeta
--!   bits[125:84]  = flux_rotor_alpha
--!   bits[167:126] = flux_rotor_beta
--!   bits[209:168] = speed_mech
--!   bits[241:210] = HIL timestamp (cycles)
--!   bits[255:242] = HIL epoch
--!
--! \author     Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       13-04-2026
--! \version    2.0
-- =============================================================================

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

use work.BilinearSolverPkg.all;

-- =============================================================================
-- Entity
-- =============================================================================
Entity HIL_AXI_Top is
    Generic (
        -- Clock
        CLK_FREQ         : natural := 100_000_000;   -- FCLK0 da EBAZ4205 (100 MHz, AXI/PWM)
        SOLVER_CLK_FREQ  : natural := 200_000_000;   -- MMCM interno para TIM_Solver/DSP

        -- Portadora NPC — 1 kHz gera IRQ confortável para Linux sem RT
        -- CARRIER_MAX = CLK_FREQ / PWM_FREQ / 2 = 50000
        -- Referencias do PS devem estar em ±CARRIER_MAX para 100% modulação
        PWM_FREQ         : natural := 1_000;

        -- NPC Modulator
        NPC_DW           : natural := 32;

        -- TIM Solver
        TIM_DW           : natural := 42;

        -- Parâmetros do motor (indução 4-polos, 0.75 kW ref)
        MOTOR_RS         : real := 0.435;
        MOTOR_RR         : real := 0.2826;
        MOTOR_LS         : real := 3.1364e-3;
        MOTOR_LR         : real := 6.3264e-3;
        MOTOR_LM         : real := 109.9442e-3;
        MOTOR_J          : real := 0.192;
        MOTOR_NPP        : real := 2.0
    );
    Port (
        clk              : in  std_logic;
        rst_n            : in  std_logic;
        solver_rst_n     : in  std_logic;

        -- ── Referências de tensão (escritas pelo PS na ISR) ──────────────────
        -- Unidade: integer signed em ±CARRIER_MAX = ±(CLK_FREQ/PWM_FREQ/2)
        -- Ex: CLK=100MHz, PWM=1kHz → CARRIER_MAX=50000 (100% modulação)
        va_ref_i         : in  std_logic_vector(NPC_DW-1 downto 0);
        vb_ref_i         : in  std_logic_vector(NPC_DW-1 downto 0);
        vc_ref_i         : in  std_logic_vector(NPC_DW-1 downto 0);

        -- ── Controle PWM (bit[0]=enable, bit[1]=clear_fault,
        --                  bit[2]=solver_reset, bits[31:3]=decim) ─────────
        pwm_ctrl_i       : in  std_logic_vector(31 downto 0);

        -- ── Barramento DC e torque de carga (Q18.14 signed → Q14.28) ─────────
        vdc_word_i       : in  std_logic_vector(31 downto 0);
        torque_word_i    : in  std_logic_vector(31 downto 0);

        -- ── Programação dos coeficientes do TIM_Solver (PS → PL) ────────────
        -- coeff_addr_i: [1:0]=matrix A/B/Y, [4:2]=row, [7:5]=col.
        coeff_we_i      : in  std_logic;
        coeff_apply_i   : in  std_logic;
        coeff_addr_i    : in  std_logic_vector(31 downto 0);
        coeff_data_i    : in  std_logic_vector(41 downto 0);

        -- ── Interrupção para o PS (1 pulso por período de portadora) ─────────
        -- Conectar a IRQ_F2P[0] no Block Design
        carrier_tick_o   : out std_logic;

        -- ── Monitoramento físico (32 MSBs de cada saída de 42 bits) ─────────
        ialpha_mon_o     : out std_logic_vector(31 downto 0);
        ibeta_mon_o      : out std_logic_vector(31 downto 0);
        flux_alpha_mon_o : out std_logic_vector(31 downto 0);
        flux_beta_mon_o  : out std_logic_vector(31 downto 0);
        speed_mon_o      : out std_logic_vector(31 downto 0);
        data_valid_mon_o : out std_logic;

        -- ── Debug bus para HIL_Regs_AXI (read-only via PS) ──────────────────
        dbg_status_o     : out std_logic_vector(31 downto 0);  -- rst_n, enable, busy, ...
        dbg_free_run_o   : out std_logic_vector(31 downto 0);  -- contador livre (clock vivo)
        dbg_carrier_o    : out std_logic_vector(31 downto 0);  -- carrier ticks
        dbg_timer_o      : out std_logic_vector(31 downto 0);  -- timer ticks do solver
        dbg_dv_latch_o   : out std_logic_vector(31 downto 0);  -- data_valid latch sticky

        -- ── PWM transition capture (read by PS via HIL_Regs_AXI) ────────────
        pwm_cap_start_i  : in  std_logic;
        pwm_cap_stop_i   : in  std_logic;
        pwm_cap_clear_i  : in  std_logic;
        pwm_cap_pop_i    : in  std_logic;
        pwm_cap_window_i : in  std_logic_vector(31 downto 0);
        pwm_cap_status_o : out std_logic_vector(31 downto 0);
        pwm_cap_data_o   : out std_logic_vector(63 downto 0);
        hil_time_o       : out std_logic_vector(31 downto 0);
        hil_epoch_o      : out std_logic_vector(31 downto 0);

        -- ── AXI4-Stream master → AXI DMA S2MM ───────────────────────────────
        m_axis_tdata     : out std_logic_vector(255 downto 0);
        m_axis_tvalid    : out std_logic;
        m_axis_tlast     : out std_logic;
        m_axis_tkeep     : out std_logic_vector(31 downto 0);
        m_axis_tready    : in  std_logic
    );
End entity HIL_AXI_Top;

-- =============================================================================
-- Architecture
-- =============================================================================
Architecture rtl of HIL_AXI_Top is


    --------------------------------------------------------------------------
    -- Encoding dos estados NPC → 4 bits (S4 S3 S2 S1)
    --------------------------------------------------------------------------
    constant NPC_STATE_POS    : std_logic_vector(3 downto 0) := "0011";  -- +Vdc/2
    constant NPC_STATE_ZERO_P : std_logic_vector(3 downto 0) := "0010";  -- dead-time from POS
    constant NPC_STATE_ZERO   : std_logic_vector(3 downto 0) := "0110";  -- neutral point
    constant NPC_STATE_ZERO_N : std_logic_vector(3 downto 0) := "0100";  -- dead-time from NEG
    constant NPC_STATE_NEG    : std_logic_vector(3 downto 0) := "1100";  -- -Vdc/2

    --------------------------------------------------------------------------
    -- Controle
    --------------------------------------------------------------------------
    signal pwm_enable_s        : std_logic;
    signal pwm_clear_s         : std_logic;
    signal pwm_solver_reset_s  : std_logic;
    -- Reset auxiliar para filtros e caminhos derivados: combina rst_n global do sistema
    -- com o bit[2] do pwm_ctrl (software-pulsable). PS pulsa esse bit para
    -- limpar estados derivados entre
    -- runs sem precisar de reload do bitstream. O TIM_Solver preserva coeficientes e usa state_clear_i.

    --------------------------------------------------------------------------
    -- Barramento DC (42 bits)
    --------------------------------------------------------------------------
    signal vdc_bus_42    : signed(TIM_DW-1 downto 0);
    signal vdc_pos       : signed(TIM_DW-1 downto 0);
    signal vdc_neg       : signed(TIM_DW-1 downto 0);
    signal torque_42     : std_logic_vector(TIM_DW-1 downto 0);

    --------------------------------------------------------------------------
    -- Saídas NPCManager (estados de gate, 4 bits por fase)
    --------------------------------------------------------------------------
    signal pwm_a         : std_logic_vector(3 downto 0);
    signal pwm_b         : std_logic_vector(3 downto 0);
    signal pwm_c         : std_logic_vector(3 downto 0);
    signal carrier_tick_s : std_logic;

    --------------------------------------------------------------------------
    -- Tensões de fase para o solver (42 bits)
    --------------------------------------------------------------------------
    signal va_motor      : std_logic_vector(TIM_DW-1 downto 0);
    signal vb_motor      : std_logic_vector(TIM_DW-1 downto 0);
    signal vc_motor      : std_logic_vector(TIM_DW-1 downto 0);
    signal va_motor_clk  : std_logic_vector(TIM_DW-1 downto 0) := (others => '0');
    signal vb_motor_clk  : std_logic_vector(TIM_DW-1 downto 0) := (others => '0');
    signal vc_motor_clk  : std_logic_vector(TIM_DW-1 downto 0) := (others => '0');
    signal torque_42_clk : std_logic_vector(TIM_DW-1 downto 0) := (others => '0');
    signal pwm_ctrl_clk  : std_logic_vector(31 downto 0) := (others => '0');

    --------------------------------------------------------------------------
    -- Saídas do TIM_Solver
    --------------------------------------------------------------------------
    signal ialpha_s      : std_logic_vector(TIM_DW-1 downto 0);
    signal ibeta_s       : std_logic_vector(TIM_DW-1 downto 0);
    signal flux_alpha_s  : std_logic_vector(TIM_DW-1 downto 0);
    signal flux_beta_s   : std_logic_vector(TIM_DW-1 downto 0);
    signal speed_s       : std_logic_vector(TIM_DW-1 downto 0);
    signal data_valid_s      : std_logic;
    -- Sticky latch: fica '1' após o primeiro pulso data_valid; limpa com rst_n.
    signal data_valid_latch  : std_logic;
    -- Contador de passos do solver (incrementa a cada data_valid_s) — extra para debug
    signal solver_step_ctr   : unsigned(31 downto 0);
    signal timer_tick_dbg_s   : std_logic;
    signal clarke_valid_dbg_s : std_logic;
    signal solver_busy_dbg_s  : std_logic;
    signal solver_done_dbg_s  : std_logic;
    signal timer_tick_toggle    : std_logic := '0';
    signal clarke_valid_toggle  : std_logic := '0';
    signal solver_done_toggle   : std_logic := '0';
    signal timer_tick_toggle_m1 : std_logic := '0';
    signal timer_tick_toggle_m2 : std_logic := '0';
    signal timer_tick_toggle_d  : std_logic := '0';
    signal clarke_valid_toggle_m1 : std_logic := '0';
    signal clarke_valid_toggle_m2 : std_logic := '0';
    signal clarke_valid_toggle_d  : std_logic := '0';
    signal solver_done_toggle_m1 : std_logic := '0';
    signal solver_done_toggle_m2 : std_logic := '0';
    signal solver_done_toggle_d  : std_logic := '0';
    signal timer_tick_ctr_solver  : unsigned(31 downto 0) := (others => '0');
    signal solver_done_ctr_solver : unsigned(31 downto 0) := (others => '0');
    signal solver_clk_div          : unsigned(7 downto 0) := (others => '0');
    signal solver_clk_alive_toggle : std_logic := '0';
    signal solver_clk_alive_m1     : std_logic := '0';
    signal solver_clk_alive_m2     : std_logic := '0';
    signal solver_clk_alive_d      : std_logic := '0';
    signal solver_rst_n_m1         : std_logic := '0';
    signal solver_rst_n_m2         : std_logic := '0';
    signal solver_clk_alive_ctr    : unsigned(29 downto 0) := (others => '0');
    signal solver_rst_sync1        : std_logic := '0';
    signal solver_rst_sync2        : std_logic := '0';
    signal solver_rst_sync_n       : std_logic := '0';
    signal solver_mmcm_rst        : std_logic;
    signal solver_clk_fb          : std_logic;
    signal solver_clk_fb_buf      : std_logic;
    signal solver_clk_mmcm        : std_logic;
    signal solver_clk_200         : std_logic;
    signal solver_clk_locked      : std_logic;

    -- Sinais sincronizados para o dominio rapido do solver (200 MHz).
    signal va_motor_solver      : std_logic_vector(TIM_DW-1 downto 0);
    signal vb_motor_solver      : std_logic_vector(TIM_DW-1 downto 0);
    signal vc_motor_solver      : std_logic_vector(TIM_DW-1 downto 0);
    signal torque_solver        : std_logic_vector(TIM_DW-1 downto 0);
    signal pwm_ctrl_solver      : std_logic_vector(31 downto 0);
    signal coeff_addr_solver    : std_logic_vector(31 downto 0);
    signal coeff_data_solver    : std_logic_vector(41 downto 0);
    signal coeff_we_meta        : std_logic := '0';
    signal coeff_we_solver      : std_logic := '0';
    signal coeff_apply_meta     : std_logic := '0';
    signal coeff_apply_solver   : std_logic := '0';
    signal solver_state_clear_s : std_logic;
    signal solver_reset_n_s     : std_logic;

    -- Snapshot do solver 200 MHz para o dominio AXI/PWM 100 MHz.
    signal solver_sample_toggle     : std_logic := '0';
    signal solver_sample_toggle_m1  : std_logic := '0';
    signal solver_sample_toggle_m2  : std_logic := '0';
    signal solver_sample_toggle_d   : std_logic := '0';
    signal solver_sample_ack_toggle : std_logic := '0';
    signal solver_sample_ack_m1_s   : std_logic := '0';
    signal solver_sample_ack_m2_s   : std_logic := '0';
    signal solver_sample_pending_s  : std_logic := '0';
    signal solver_sample_pulse      : std_logic := '0';
    signal ialpha_snap_solver       : std_logic_vector(TIM_DW-1 downto 0);
    signal ibeta_snap_solver        : std_logic_vector(TIM_DW-1 downto 0);
    signal flux_alpha_snap_solver   : std_logic_vector(TIM_DW-1 downto 0);
    signal flux_beta_snap_solver    : std_logic_vector(TIM_DW-1 downto 0);
    signal speed_snap_solver        : std_logic_vector(TIM_DW-1 downto 0);
    signal ialpha_raw_axi           : std_logic_vector(TIM_DW-1 downto 0);
    signal ibeta_raw_axi            : std_logic_vector(TIM_DW-1 downto 0);
    signal flux_alpha_raw_axi       : std_logic_vector(TIM_DW-1 downto 0);
    signal flux_beta_raw_axi        : std_logic_vector(TIM_DW-1 downto 0);
    signal speed_raw_axi            : std_logic_vector(TIM_DW-1 downto 0);
    signal ialpha_aa_axi            : std_logic_vector(TIM_DW-1 downto 0);
    signal ibeta_aa_axi             : std_logic_vector(TIM_DW-1 downto 0);
    signal flux_alpha_aa_axi        : std_logic_vector(TIM_DW-1 downto 0);
    signal flux_beta_aa_axi         : std_logic_vector(TIM_DW-1 downto 0);
    signal speed_aa_axi             : std_logic_vector(TIM_DW-1 downto 0);
    signal timer_tick_dbg_axi       : std_logic := '0';
    signal clarke_valid_dbg_axi     : std_logic := '0';
    signal solver_busy_dbg_axi      : std_logic := '0';
    signal solver_done_dbg_axi      : std_logic := '0';
    signal data_valid_axi           : std_logic := '0';

    -- Use an integer step at the synthesizable boundary. Vivado BD/module_ref
    -- can mishandle real generics and turn the solver timer into a constant zero.
    constant SOLVER_STEP_CYCLES : natural := 26;
    signal free_run_ctr       : unsigned(31 downto 0) := (others => '0');
    signal carrier_tick_ctr   : unsigned(31 downto 0) := (others => '0');
    signal timer_tick_ctr     : unsigned(31 downto 0) := (others => '0');
    signal solver_done_ctr    : unsigned(31 downto 0) := (others => '0');
    signal debug_status_word  : std_logic_vector(31 downto 0) := x"D0000000";

    -- mark_debug: força o Vivado a preservar sinais internos que alimentam os
    -- outputs do módulo através do boundary OOC de link_design.
    attribute mark_debug : string;
    attribute mark_debug of data_valid_latch : signal is "true";
    attribute mark_debug of carrier_tick_s   : signal is "true";

    --------------------------------------------------------------------------
    -- Registrador AXI4-Stream + Decimador
    --------------------------------------------------------------------------
    constant AXIS_DMA_BURST_FRAMES_C : natural := 128;
    signal axis_tdata_r   : std_logic_vector(255 downto 0);
    signal axis_tvalid_r  : std_logic;
    signal axis_tlast_r   : std_logic;
    signal axis_frame_cnt : unsigned(6 downto 0);
    signal decim_count    : unsigned(29 downto 0);
    signal decim_ratio    : unsigned(29 downto 0);

    --------------------------------------------------------------------------
    -- Anti-aliasing filter — 2nd-order Butterworth, 5 channels on ONE shared
    -- datapath (inlined to avoid a block-design module-reference dependency on a
    -- separate sub-module). Chamberlin SVF, multiplier-less: f1=2^-5,
    -- q1=1.40625. Decoupled recurrence (lp[n], bp[n] from old state only),
    -- 3-stage pipeline, one channel fed per clock after data_valid.
    --   lp[n] = lp + bp/32
    --   bp[n] = bp + x/32 - lp/32 - (bp*1.4375)/32
    --------------------------------------------------------------------------
    constant SVF_GUARD : natural := 4;
    constant SVF_FSH   : natural := 5;
    constant SVF_W     : natural := TIM_DW + SVF_GUARD + 2;   -- 48-bit state
    type svf_state_t is array (0 to 4) of signed(SVF_W-1 downto 0);
    type svf_in_t    is array (0 to 4) of std_logic_vector(TIM_DW-1 downto 0);
    signal svf_lp, svf_bp : svf_state_t := (others => (others => '0'));
    signal svf_xin        : svf_in_t;
    signal svf_feeding    : std_logic := '0';
    signal svf_fcnt       : integer range 0 to 4 := 0;
    signal svf_s1_v, svf_s2_v   : std_logic := '0';
    signal svf_s1_ch, svf_s2_ch : integer range 0 to 4 := 0;
    signal svf_s1_lpnew, svf_s1_Ka, svf_s1_Kb, svf_s1_bx, svf_s1_lp5 : signed(SVF_W-1 downto 0) := (others => '0');
    signal svf_s2_lpnew, svf_s2_Kbp, svf_s2_bx : signed(SVF_W-1 downto 0) := (others => '0');

    --------------------------------------------------------------------------
    -- PWM transition capture FIFO (100 MHz clock domain).
    --------------------------------------------------------------------------
    constant PWM_CAP_DEPTH_C : natural := 2048;
    type pwm_cap_mem_t is array (0 to PWM_CAP_DEPTH_C-1) of std_logic_vector(63 downto 0);
    signal pwm_cap_mem       : pwm_cap_mem_t;
    signal pwm_cap_wr        : natural range 0 to PWM_CAP_DEPTH_C-1 := 0;
    signal pwm_cap_rd        : natural range 0 to PWM_CAP_DEPTH_C-1 := 0;
    signal pwm_cap_count     : natural range 0 to PWM_CAP_DEPTH_C := 0;
    signal pwm_cap_active    : std_logic := '0';
    signal pwm_cap_overflow  : std_logic := '0';
    signal pwm_cap_time      : unsigned(31 downto 0) := (others => '0');
    signal pwm_cap_epoch     : unsigned(15 downto 0) := (others => '0');
    signal pwm_enable_d      : std_logic := '0';
    signal pwm_cap_force     : std_logic := '0';
    signal pwm_a_prev        : std_logic_vector(3 downto 0) := (others => '0');
    signal pwm_b_prev        : std_logic_vector(3 downto 0) := (others => '0');
    signal pwm_c_prev        : std_logic_vector(3 downto 0) := (others => '0');
    constant PWM_CAP_CTRL_MAGIC_C : std_logic_vector(31 downto 0) := x"FFFF0100";
    constant PWM_CAP_POP_MAGIC_C  : std_logic_vector(31 downto 0) := x"FFFF0104";
    signal pwm_cap_ctrl_cmd  : std_logic;
    signal pwm_cap_pop_cmd   : std_logic;
    signal pwm_cap_start_cmd : std_logic;
    signal pwm_cap_stop_cmd  : std_logic;
    signal pwm_cap_clear_cmd : std_logic;
    signal pwm_cap_data_s   : std_logic_vector(63 downto 0);
    signal pwm_cap_status_s : std_logic_vector(31 downto 0);
    signal hil_time_s       : std_logic_vector(31 downto 0);
    signal hil_epoch_s      : std_logic_vector(31 downto 0);

Begin

    pwm_cap_ctrl_cmd  <= '1' when coeff_we_i = '1' and coeff_addr_i = PWM_CAP_CTRL_MAGIC_C else '0';
    pwm_cap_pop_cmd   <= '1' when coeff_we_i = '1' and coeff_addr_i = PWM_CAP_POP_MAGIC_C else '0';
    pwm_cap_start_cmd <= pwm_cap_ctrl_cmd and coeff_data_i(0);
    pwm_cap_stop_cmd  <= pwm_cap_ctrl_cmd and coeff_data_i(1);
    pwm_cap_clear_cmd <= pwm_cap_ctrl_cmd and coeff_data_i(2);

    --------------------------------------------------------------------------
    -- Clock do solver: 200 MHz gerado na PL a partir do FCLK0 de 100 MHz.
    -- O FCLK1 do PS7 não fica vivo na EBAZ atual após fpgautil.
    --------------------------------------------------------------------------
    solver_mmcm_rst <= not rst_n;

    Solver_MMCM : MMCME2_BASE
    generic map (
        BANDWIDTH          => "OPTIMIZED",
        CLKFBOUT_MULT_F    => 10.0,
        CLKFBOUT_PHASE     => 0.0,
        CLKIN1_PERIOD      => 10.0,
        CLKOUT0_DIVIDE_F   => 5.0,
        CLKOUT0_DUTY_CYCLE => 0.5,
        CLKOUT0_PHASE      => 0.0,
        DIVCLK_DIVIDE      => 1,
        STARTUP_WAIT       => false
    )
    port map (
        CLKIN1      => clk,
        CLKFBIN     => solver_clk_fb_buf,
        CLKFBOUT    => solver_clk_fb,
        CLKFBOUTB   => open,
        CLKOUT0     => solver_clk_mmcm,
        CLKOUT0B    => open,
        CLKOUT1     => open,
        CLKOUT1B    => open,
        CLKOUT2     => open,
        CLKOUT2B    => open,
        CLKOUT3     => open,
        CLKOUT3B    => open,
        CLKOUT4     => open,
        CLKOUT5     => open,
        CLKOUT6     => open,
        LOCKED      => solver_clk_locked,
        PWRDWN      => '0',
        RST         => solver_mmcm_rst
    );

    Solver_CLKFB_BUFG : BUFG port map (I => solver_clk_fb, O => solver_clk_fb_buf);
    Solver_CLK_BUFG   : BUFG port map (I => solver_clk_mmcm, O => solver_clk_200);

    carrier_tick_o <= carrier_tick_s;

    --------------------------------------------------------------------------
    -- Desempacotamento do controle PWM
    --------------------------------------------------------------------------
    pwm_enable_s       <= pwm_ctrl_i(0);
    pwm_clear_s        <= pwm_ctrl_i(1);
    pwm_solver_reset_s <= pwm_ctrl_i(2);
    -- Active-low reset para o TIM_Solver: assertado quando rst_n global cai
    -- OU quando o PS escreve bit[2]=1 no pwm_ctrl.

    --------------------------------------------------------------------------
    -- Conversão Q18.14 (32 bits do PS) → Q14.28 (42 bits interno do solver)
    --   Shift_left 14 equivale a multiplicar por 2^14, mantendo unidade física
    --------------------------------------------------------------------------
    vdc_bus_42 <= shift_left(resize(signed(vdc_word_i),    TIM_DW), 14);
    torque_42  <= std_logic_vector(shift_left(resize(signed(torque_word_i), TIM_DW), 14));

    --------------------------------------------------------------------------
    -- Barramento DC: +Vdc/2 e −Vdc/2 (tensões de fase do inversor NPC)
    --------------------------------------------------------------------------
    vdc_pos <= shift_right(vdc_bus_42, 1);
    vdc_neg <= -shift_right(vdc_bus_42, 1);

    --------------------------------------------------------------------------
    -- NPCManager — portadora triangular + gate drivers
    --   carrier_tick_o = pulso no valley → 1 pulso por período (1 kHz)
    --   O NPCModulator trava va/vb/vc no valley (sample_tick)
    --   Portanto o PS tem todo o período entre IRQs para calcular e escrever
    --------------------------------------------------------------------------
    NPCManager_Inst : entity work.NPCManager
    generic map (
        CLK_FREQ        => CLK_FREQ,
        PWM_FREQ        => PWM_FREQ,
        DATA_WIDTH      => NPC_DW,
        LOAD_BOTH_EDGES => false,   -- trava apenas no valley (sincroniza com IRQ)
        OUTPUT_REG      => true,
        WAIT_STATE_CNT  => CLK_FREQ / 1000  -- 1 ms de wait state na inicialização
    )
    port map (
        sysclk          => clk,
        reset_n         => rst_n,
        pwm_enb_i       => pwm_enable_s,
        clear_i         => pwm_clear_s,
        -- Referências escritas pelo PS via HIL_Regs_AXI
        va_ref_i        => va_ref_i,
        vb_ref_i        => vb_ref_i,
        vc_ref_i        => vc_ref_i,
        -- Tick de portadora → IRQ para o PS
        carrier_tick_o  => carrier_tick_s,
        sample_tick_o   => open,
        -- Estados de gate (4 bits por fase)
        pwm_a_o         => pwm_a,
        pwm_b_o         => pwm_b,
        pwm_c_o         => pwm_c,
        pwm_on_o        => open,
        fault_o         => open,
        fs_fault_o      => open,
        minw_fault_o    => open
    );

    --------------------------------------------------------------------------
    -- NPC_to_Voltage — converte estado de gate em tensão para o solver.
    -- Dead-time não é comandado como zero: o gate driver emite "0010" ao sair
    -- de POS e "0100" ao sair de NEG; modelamos esses estados como meio nível
    -- para não injetar notch artificial de 0 V na planta ideal.
    --------------------------------------------------------------------------
    NPC_to_Voltage : process(pwm_a, pwm_b, pwm_c, vdc_pos, vdc_neg, vdc_bus_42)
    begin
        case pwm_a is
            when NPC_STATE_POS    => va_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_ZERO_P => va_motor <= std_logic_vector(shift_right(vdc_bus_42, 2));
            when NPC_STATE_NEG    => va_motor <= std_logic_vector(vdc_neg);
            when NPC_STATE_ZERO_N => va_motor <= std_logic_vector(-shift_right(vdc_bus_42, 2));
            when others           => va_motor <= (others => '0');
        end case;

        case pwm_b is
            when NPC_STATE_POS    => vb_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_ZERO_P => vb_motor <= std_logic_vector(shift_right(vdc_bus_42, 2));
            when NPC_STATE_NEG    => vb_motor <= std_logic_vector(vdc_neg);
            when NPC_STATE_ZERO_N => vb_motor <= std_logic_vector(-shift_right(vdc_bus_42, 2));
            when others           => vb_motor <= (others => '0');
        end case;

        case pwm_c is
            when NPC_STATE_POS    => vc_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_ZERO_P => vc_motor <= std_logic_vector(shift_right(vdc_bus_42, 2));
            when NPC_STATE_NEG    => vc_motor <= std_logic_vector(vdc_neg);
            when NPC_STATE_ZERO_N => vc_motor <= std_logic_vector(-shift_right(vdc_bus_42, 2));
            when others           => vc_motor <= (others => '0');
        end case;
    end process NPC_to_Voltage;

    --------------------------------------------------------------------------
    -- Barreiras registradas no dominio AXI/PWM. O solver de 200 MHz recebe
    -- uma imagem ja assentada das tensoes PWM e dos comandos lentos, evitando
    -- amostrar glitches combinacionais de gate/Vdc no meio de uma transicao.
    --------------------------------------------------------------------------
    Solver_Input_Stage_100M : process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                va_motor_clk  <= (others => '0');
                vb_motor_clk  <= (others => '0');
                vc_motor_clk  <= (others => '0');
                torque_42_clk <= (others => '0');
                pwm_ctrl_clk  <= (others => '0');
            else
                va_motor_clk  <= va_motor;
                vb_motor_clk  <= vb_motor;
                vc_motor_clk  <= vc_motor;
                torque_42_clk <= torque_42;
                pwm_ctrl_clk  <= pwm_ctrl_i;
            end if;
        end if;
    end process Solver_Input_Stage_100M;

    --------------------------------------------------------------------------
    -- Transferencia 100 MHz -> 200 MHz para entradas do solver.
    --------------------------------------------------------------------------
    Solver_Input_CDC : process(solver_clk_200)
    begin
        if rising_edge(solver_clk_200) then
            if solver_rst_sync_n = '0' then
                va_motor_solver      <= (others => '0');
                vb_motor_solver      <= (others => '0');
                vc_motor_solver      <= (others => '0');
                torque_solver        <= (others => '0');
                pwm_ctrl_solver      <= (others => '0');
                coeff_addr_solver    <= (others => '0');
                coeff_data_solver    <= (others => '0');
                coeff_we_meta        <= '0';
                coeff_we_solver      <= '0';
                coeff_apply_meta   <= '0';
                coeff_apply_solver <= '0';
            else
                va_motor_solver      <= va_motor_clk;
                vb_motor_solver      <= vb_motor_clk;
                vc_motor_solver      <= vc_motor_clk;
                torque_solver        <= torque_42_clk;
                pwm_ctrl_solver      <= pwm_ctrl_clk;
                coeff_addr_solver    <= coeff_addr_i;
                coeff_data_solver    <= coeff_data_i;
                coeff_we_meta        <= coeff_we_i;
                coeff_we_solver      <= coeff_we_meta;
                coeff_apply_meta   <= coeff_apply_i;
                coeff_apply_solver <= coeff_apply_meta;
            end if;
        end if;
    end process Solver_Input_CDC;

    Solver_Reset_Sync : process(solver_clk_200, rst_n, solver_clk_locked)
    begin
        if rst_n = '0' or solver_clk_locked = '0' then
            solver_rst_sync1 <= '0';
            solver_rst_sync2 <= '0';
        elsif rising_edge(solver_clk_200) then
            solver_rst_sync1 <= '1';
            solver_rst_sync2 <= solver_rst_sync1;
        end if;
    end process Solver_Reset_Sync;

    solver_rst_sync_n   <= solver_rst_sync2;
    solver_state_clear_s <= pwm_ctrl_solver(2);
    -- O pulso de solver_reset deve limpar o TIM_Solver inteiro: Xvec, timer,
    -- Clarke, handler bilinear e pipelines internos. O PS reprograma os
    -- coeficientes ativos logo apos liberar o reset, preservando motor custom.
    solver_reset_n_s     <= solver_rst_sync_n and not solver_state_clear_s;

    --------------------------------------------------------------------------
    -- TIM_Solver — modelo de motor de indução trifásico
    --------------------------------------------------------------------------
    TIM_Solver_Inst : entity work.TIM_Solver
    generic map (
        DATA_WIDTH       => TIM_DW,
        CLOCK_FREQUENCY     => SOLVER_CLK_FREQ,
        SOLVER_STEP_CYCLES => SOLVER_STEP_CYCLES,
        rs               => MOTOR_RS,
        rr               => MOTOR_RR,
        ls               => MOTOR_LS,
        lr               => MOTOR_LR,
        lm               => MOTOR_LM,
        j                => MOTOR_J,
        npp              => MOTOR_NPP
    )
    port map (
        sysclk              => solver_clk_200,
        reset_n             => solver_reset_n_s,
        state_clear_i       => solver_state_clear_s,
        va_i                => va_motor_solver,
        vb_i                => vb_motor_solver,
        vc_i                => vc_motor_solver,
        torque_load_i       => torque_solver,
        coeff_we_i          => coeff_we_solver,
        coeff_apply_i       => coeff_apply_solver,
        coeff_matrix_i      => coeff_addr_solver(1 downto 0),
        coeff_row_i         => coeff_addr_solver(4 downto 2),
        coeff_col_i         => coeff_addr_solver(7 downto 5),
        coeff_data_i        => coeff_data_solver,
        ialpha_o            => ialpha_s,
        ibeta_o             => ibeta_s,
        flux_rotor_alpha_o  => flux_alpha_s,
        flux_rotor_beta_o   => flux_beta_s,
        speed_mech_o        => speed_s,
        data_valid_o        => data_valid_s,
        timer_tick_dbg_o    => timer_tick_dbg_s,
        clarke_valid_dbg_o  => clarke_valid_dbg_s,
        solver_busy_dbg_o   => solver_busy_dbg_s,
        solver_done_dbg_o   => solver_done_dbg_s
    );

    --------------------------------------------------------------------------
    -- Anti-aliasing low-pass para o caminho de DECIMADOR + monitores GPIO.
    --   Butterworth 2ª ordem (Chamberlin SVF, multiplier-less), fc ≈ 40 kHz.
    --
    -- Dimensionamento: a telemetria DMA decima 7.69 MHz → 100 kHz (Nyquist
    -- 50 kHz). fc=40 kHz passa o ripple PWM real (carrier 1 kHz + harmônicos)
    -- e corta antes do Nyquist: −3 dB @40 kHz, −16.6 dB @100 kHz, −28.5 dB
    -- @200 kHz. Ao contrário do IIR de 1ª ordem/1.15 kHz anterior, este NÃO
    -- mascara o ripple físico — só remove o que a amostragem não representa.
    --------------------------------------------------------------------------
    -- One shared SVF datapath serves all 5 channels (multiplexed) to keep the
    -- filter logic small — 5 separate instances added enough congestion to push
    -- the 200 MHz solver path into a timing violation. Inlined (no sub-module)
    -- so the block-design module reference reliably picks up the change.
    svf_xin(0) <= ialpha_raw_axi;
    svf_xin(1) <= ibeta_raw_axi;
    svf_xin(2) <= flux_alpha_raw_axi;
    svf_xin(3) <= flux_beta_raw_axi;
    svf_xin(4) <= speed_raw_axi;

    ialpha_aa_axi     <= std_logic_vector(resize(shift_right(svf_lp(0), SVF_GUARD), TIM_DW));
    ibeta_aa_axi      <= std_logic_vector(resize(shift_right(svf_lp(1), SVF_GUARD), TIM_DW));
    flux_alpha_aa_axi <= std_logic_vector(resize(shift_right(svf_lp(2), SVF_GUARD), TIM_DW));
    flux_beta_aa_axi  <= std_logic_vector(resize(shift_right(svf_lp(3), SVF_GUARD), TIM_DW));
    speed_aa_axi      <= std_logic_vector(resize(shift_right(svf_lp(4), SVF_GUARD), TIM_DW));

    SVF_Filter : process(clk, rst_n)
        variable xext : signed(SVF_W-1 downto 0);
        variable lpc, bpc : signed(SVF_W-1 downto 0);
    begin
        if rst_n = '0' then
            svf_lp <= (others => (others => '0'));
            svf_bp <= (others => (others => '0'));
            svf_feeding <= '0'; svf_fcnt <= 0;
            svf_s1_v <= '0'; svf_s2_v <= '0';
        elsif rising_edge(clk) then
            -- Stage 3: write back final state
            if svf_s2_v = '1' then
                svf_lp(svf_s2_ch) <= svf_s2_lpnew;
                svf_bp(svf_s2_ch) <= svf_s2_bx - shift_right(svf_s2_Kbp, SVF_FSH);
            end if;
            svf_s2_v <= svf_s1_v;

            -- Stage 2: combine partials
            if svf_s1_v = '1' then
                svf_s2_ch    <= svf_s1_ch;
                svf_s2_lpnew <= svf_s1_lpnew;
                svf_s2_Kbp   <= svf_s1_Ka + svf_s1_Kb;
                svf_s2_bx    <= svf_s1_bx - svf_s1_lp5;
            end if;

            -- Stage 1: read one channel, level-1 parallel adds
            svf_s1_v <= svf_feeding;
            if svf_feeding = '1' then
                lpc  := svf_lp(svf_fcnt);
                bpc  := svf_bp(svf_fcnt);
                xext := shift_left(resize(signed(svf_xin(svf_fcnt)), SVF_W), SVF_GUARD);
                svf_s1_ch    <= svf_fcnt;
                svf_s1_lpnew <= lpc + shift_right(bpc, SVF_FSH);
                svf_s1_Ka    <= bpc + shift_right(bpc, 2);
                svf_s1_Kb    <= shift_right(bpc, 3) + shift_right(bpc, 4);
                svf_s1_bx    <= bpc + shift_right(xext, SVF_FSH);
                svf_s1_lp5   <= shift_right(lpc, SVF_FSH);
                if svf_fcnt = 4 then
                    svf_feeding <= '0';
                else
                    svf_fcnt <= svf_fcnt + 1;
                end if;
            end if;

            -- Start the per-sample sweep on data_valid
            if data_valid_axi = '1' then
                svf_feeding <= '1';
                svf_fcnt    <= 0;
            end if;
        end if;
    end process SVF_Filter;

    --------------------------------------------------------------------------
    -- CDC 200 MHz -> 100 MHz: publica uma amostra filtrada por toggle.
    --------------------------------------------------------------------------
    Solver_Output_Snapshot : process(solver_clk_200)
    begin
        if rising_edge(solver_clk_200) then
            solver_clk_div <= solver_clk_div + 1;
            if solver_clk_div = x"FF" then
                solver_clk_alive_toggle <= not solver_clk_alive_toggle;
            end if;
            if solver_rst_sync_n = '0' then
                solver_sample_toggle    <= '0';
                solver_sample_ack_m1_s  <= '0';
                solver_sample_ack_m2_s  <= '0';
                solver_sample_pending_s <= '0';
                ialpha_snap_solver      <= (others => '0');
                ibeta_snap_solver       <= (others => '0');
                flux_alpha_snap_solver  <= (others => '0');
                flux_beta_snap_solver   <= (others => '0');
                speed_snap_solver       <= (others => '0');
                timer_tick_toggle       <= '0';
                clarke_valid_toggle     <= '0';
                solver_done_toggle      <= '0';
                timer_tick_ctr_solver   <= (others => '0');
                solver_done_ctr_solver  <= (others => '0');
            else
                solver_sample_ack_m1_s <= solver_sample_ack_toggle;
                solver_sample_ack_m2_s <= solver_sample_ack_m1_s;
                if solver_sample_pending_s = '1' and
                   solver_sample_ack_m2_s = solver_sample_toggle then
                    solver_sample_pending_s <= '0';
                end if;
                if data_valid_s = '1' and solver_sample_pending_s = '0' then
                    ialpha_snap_solver      <= ialpha_s;
                    ibeta_snap_solver       <= ibeta_s;
                    flux_alpha_snap_solver  <= flux_alpha_s;
                    flux_beta_snap_solver   <= flux_beta_s;
                    speed_snap_solver       <= speed_s;
                    solver_sample_toggle    <= not solver_sample_toggle;
                    solver_sample_pending_s <= '1';
                end if;
                if timer_tick_dbg_s = '1' then
                    timer_tick_toggle <= not timer_tick_toggle;
                    timer_tick_ctr_solver <= timer_tick_ctr_solver + 1;
                end if;
                if clarke_valid_dbg_s = '1' then
                    clarke_valid_toggle <= not clarke_valid_toggle;
                end if;
                if solver_done_dbg_s = '1' then
                    solver_done_toggle <= not solver_done_toggle;
                    solver_done_ctr_solver <= solver_done_ctr_solver + 1;
                end if;
            end if;
        end if;
    end process Solver_Output_Snapshot;

    Solver_Output_CDC : process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                solver_sample_toggle_m1 <= '0';
                solver_sample_toggle_m2 <= '0';
                solver_sample_toggle_d  <= '0';
                solver_sample_ack_toggle <= '0';
                solver_sample_pulse     <= '0';
                timer_tick_toggle_m1  <= '0';
                timer_tick_toggle_m2  <= '0';
                timer_tick_toggle_d   <= '0';
                clarke_valid_toggle_m1 <= '0';
                clarke_valid_toggle_m2 <= '0';
                clarke_valid_toggle_d  <= '0';
                solver_done_toggle_m1 <= '0';
                solver_done_toggle_m2 <= '0';
                solver_done_toggle_d  <= '0';
                solver_clk_alive_m1 <= '0';
                solver_clk_alive_m2 <= '0';
                solver_clk_alive_d  <= '0';
                solver_rst_n_m1     <= '0';
                solver_rst_n_m2     <= '0';
                ialpha_raw_axi          <= (others => '0');
                ibeta_raw_axi           <= (others => '0');
                flux_alpha_raw_axi      <= (others => '0');
                flux_beta_raw_axi       <= (others => '0');
                speed_raw_axi           <= (others => '0');
                timer_tick_dbg_axi      <= '0';
                clarke_valid_dbg_axi    <= '0';
                solver_busy_dbg_axi     <= '0';
                solver_done_dbg_axi     <= '0';
                data_valid_axi          <= '0';
            else
                solver_sample_toggle_m1 <= solver_sample_toggle;
                solver_sample_toggle_m2 <= solver_sample_toggle_m1;
                solver_sample_toggle_d  <= solver_sample_toggle_m2;
                solver_sample_pulse     <= solver_sample_toggle_m2 xor solver_sample_toggle_d;
                timer_tick_toggle_m1    <= timer_tick_toggle;
                timer_tick_toggle_m2    <= timer_tick_toggle_m1;
                timer_tick_toggle_d     <= timer_tick_toggle_m2;
                clarke_valid_toggle_m1  <= clarke_valid_toggle;
                clarke_valid_toggle_m2  <= clarke_valid_toggle_m1;
                clarke_valid_toggle_d   <= clarke_valid_toggle_m2;
                solver_done_toggle_m1   <= solver_done_toggle;
                solver_done_toggle_m2   <= solver_done_toggle_m1;
                solver_done_toggle_d    <= solver_done_toggle_m2;
                solver_clk_alive_m1 <= solver_clk_alive_toggle;
                solver_clk_alive_m2 <= solver_clk_alive_m1;
                solver_clk_alive_d  <= solver_clk_alive_m2;
                solver_rst_n_m1     <= solver_rst_sync_n;
                solver_rst_n_m2     <= solver_rst_n_m1;
                timer_tick_dbg_axi      <= timer_tick_toggle_m2 xor timer_tick_toggle_d;
                clarke_valid_dbg_axi    <= clarke_valid_toggle_m2 xor clarke_valid_toggle_d;
                solver_busy_dbg_axi     <= solver_busy_dbg_s;
                solver_done_dbg_axi     <= solver_done_toggle_m2 xor solver_done_toggle_d;
                data_valid_axi          <= solver_sample_toggle_m2 xor solver_sample_toggle_d;
                if (solver_sample_toggle_m2 xor solver_sample_toggle_d) = '1' then
                    ialpha_raw_axi          <= ialpha_snap_solver;
                    ibeta_raw_axi           <= ibeta_snap_solver;
                    flux_alpha_raw_axi      <= flux_alpha_snap_solver;
                    flux_beta_raw_axi       <= flux_beta_snap_solver;
                    speed_raw_axi           <= speed_snap_solver;
                    solver_sample_ack_toggle <= solver_sample_toggle_m2;
                end if;
            end if;
        end if;
    end process Solver_Output_CDC;

    --------------------------------------------------------------------------
    -- Monitoramento físico (FILTRADO): 32 MSBs do sinal pós-IIR (fc=1.15 kHz).
    --   O polling do PS via /dev/mem é assíncrono (~10 kHz com jitter); o
    --   IIR previne aliasing dessa amostragem. Tanto GPIO quanto DMA leem
    --   este mesmo sinal filtrado.
    --   mark_debug nos ports força preservação pelo link_design (OOC DCP fix)
    --------------------------------------------------------------------------
    ialpha_mon_o     <= ialpha_aa_axi(TIM_DW-1 downto TIM_DW-32);
    ibeta_mon_o      <= ibeta_aa_axi(TIM_DW-1 downto TIM_DW-32);
    flux_alpha_mon_o <= flux_alpha_aa_axi(TIM_DW-1 downto TIM_DW-32);
    flux_beta_mon_o  <= flux_beta_aa_axi(TIM_DW-1 downto TIM_DW-32);
    speed_mon_o      <= speed_aa_axi(TIM_DW-1 downto TIM_DW-32);
    data_valid_mon_o <= data_valid_latch;


    --------------------------------------------------------------------------
    -- PWM transition event capture.
    -- Event word: [31:0]=timestamp, [35:32]=A, [39:36]=B, [43:40]=C,
    -- [47:44]=changed mask, [63:48]=epoch. Capture auto-starts on PWM enable
    -- rising edge so every HIL Run begins a new epoch at t=0.
    --------------------------------------------------------------------------
    PWM_Capture : process(clk)
        variable count_v : natural range 0 to PWM_CAP_DEPTH_C;
        variable wr_v    : natural range 0 to PWM_CAP_DEPTH_C-1;
        variable rd_v    : natural range 0 to PWM_CAP_DEPTH_C-1;
        variable mask_v  : std_logic_vector(3 downto 0);
        variable event_v : std_logic_vector(63 downto 0);
        variable changed_v : boolean;
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                pwm_cap_wr       <= 0;
                pwm_cap_rd       <= 0;
                pwm_cap_count    <= 0;
                pwm_cap_active   <= '0';
                pwm_cap_overflow <= '0';
                pwm_cap_time     <= (others => '0');
                pwm_cap_epoch    <= (others => '0');
                pwm_enable_d     <= '0';
                pwm_cap_force    <= '0';
                pwm_a_prev       <= (others => '0');
                pwm_b_prev       <= (others => '0');
                pwm_c_prev       <= (others => '0');
            else
                count_v := pwm_cap_count;
                wr_v    := pwm_cap_wr;
                rd_v    := pwm_cap_rd;
                pwm_enable_d <= pwm_enable_s;

                if pwm_cap_pop_cmd = '1' and count_v > 0 then
                    if rd_v = PWM_CAP_DEPTH_C - 1 then
                        rd_v := 0;
                    else
                        rd_v := rd_v + 1;
                    end if;
                    count_v := count_v - 1;
                end if;

                if pwm_cap_clear_cmd = '1' then
                    wr_v := 0;
                    rd_v := 0;
                    count_v := 0;
                    pwm_cap_overflow <= '0';
                end if;

                if (pwm_enable_s = '1' and pwm_enable_d = '0') or pwm_cap_start_cmd = '1' then
                    wr_v := 0;
                    rd_v := 0;
                    count_v := 0;
                    pwm_cap_active <= '1';
                    pwm_cap_overflow <= '0';
                    pwm_cap_time <= (others => '0');
                    pwm_cap_epoch <= pwm_cap_epoch + 1;
                    pwm_cap_force <= '1';
                elsif pwm_cap_stop_cmd = '1' or pwm_enable_s = '0' then
                    pwm_cap_active <= '0';
                end if;

                if pwm_cap_active = '1' then
                    mask_v := (others => '0');
                    if pwm_a /= pwm_a_prev then mask_v(0) := '1'; end if;
                    if pwm_b /= pwm_b_prev then mask_v(1) := '1'; end if;
                    if pwm_c /= pwm_c_prev then mask_v(2) := '1'; end if;
                    changed_v := mask_v(2 downto 0) /= "000";

                    if changed_v or pwm_cap_force = '1' then
                        event_v := (others => '0');
                        event_v(31 downto 0)  := std_logic_vector(pwm_cap_time);
                        event_v(35 downto 32) := pwm_a;
                        event_v(39 downto 36) := pwm_b;
                        event_v(43 downto 40) := pwm_c;
                        event_v(47 downto 44) := mask_v;
                        event_v(63 downto 48) := std_logic_vector(pwm_cap_epoch);
                        if count_v < PWM_CAP_DEPTH_C then
                            pwm_cap_mem(wr_v) <= event_v;
                            if wr_v = PWM_CAP_DEPTH_C - 1 then
                                wr_v := 0;
                            else
                                wr_v := wr_v + 1;
                            end if;
                            count_v := count_v + 1;
                        else
                            pwm_cap_overflow <= '1';
                        end if;
                        pwm_a_prev <= pwm_a;
                        pwm_b_prev <= pwm_b;
                        pwm_c_prev <= pwm_c;
                        pwm_cap_force <= '0';
                    end if;

                    pwm_cap_time <= pwm_cap_time + 1;
                    if unsigned(pwm_cap_window_i) /= 0 and pwm_cap_time >= unsigned(pwm_cap_window_i) then
                        pwm_cap_active <= '0';
                    end if;
                else
                    pwm_a_prev <= pwm_a;
                    pwm_b_prev <= pwm_b;
                    pwm_c_prev <= pwm_c;
                end if;

                pwm_cap_wr    <= wr_v;
                pwm_cap_rd    <= rd_v;
                pwm_cap_count <= count_v;
            end if;
        end if;
    end process PWM_Capture;

    pwm_cap_data_s <= pwm_cap_mem(pwm_cap_rd) when pwm_cap_count > 0 else (others => '0');
    hil_time_s <= std_logic_vector(pwm_cap_time);
    hil_epoch_s <= x"0000" & std_logic_vector(pwm_cap_epoch);
    pwm_cap_status_s(0) <= pwm_cap_active;
    pwm_cap_status_s(1) <= pwm_cap_overflow;
    pwm_cap_status_s(2) <= '1' when pwm_cap_count = 0 else '0';
    pwm_cap_status_s(3) <= '1' when pwm_cap_count = PWM_CAP_DEPTH_C else '0';
    pwm_cap_status_s(15 downto 4) <= (others => '0');
    pwm_cap_status_s(31 downto 16) <= std_logic_vector(to_unsigned(pwm_cap_count, 16));
    pwm_cap_data_o <= pwm_cap_data_s;
    pwm_cap_status_o <= pwm_cap_status_s;
    hil_time_o <= hil_time_s;
    hil_epoch_o <= hil_epoch_s;

    --------------------------------------------------------------------------
    -- Debug bus exposto via HIL_Regs_AXI (não interfere nos monitores físicos)
    --------------------------------------------------------------------------
    dbg_status_o   <= pwm_cap_status_s;
    dbg_free_run_o <= pwm_cap_data_s(31 downto 0);
    dbg_carrier_o  <= pwm_cap_data_s(63 downto 32);
    dbg_timer_o    <= hil_time_s;
    dbg_dv_latch_o <= hil_epoch_s;

    Debug_Status : process(rst_n, pwm_enable_s, pwm_clear_s, carrier_tick_s,
                           timer_tick_dbg_axi, clarke_valid_dbg_axi, solver_busy_dbg_axi,
                           solver_done_dbg_axi, data_valid_axi, data_valid_latch,
                           m_axis_tready, axis_tvalid_r, pwm_a, pwm_b, pwm_c,
                           pwm_ctrl_i)
        variable s : std_logic_vector(31 downto 0);
    begin
        s := x"D0000000";
        s(0)            := rst_n;
        s(1)            := pwm_enable_s;
        s(2)            := pwm_clear_s;
        s(3)            := carrier_tick_s;
        s(4)            := timer_tick_dbg_axi;
        s(5)            := clarke_valid_dbg_axi;
        s(6)            := solver_busy_dbg_axi;
        s(7)            := solver_done_dbg_axi;
        s(8)            := data_valid_axi;
        s(9)            := data_valid_latch;
        s(10)           := m_axis_tready;
        s(11)           := axis_tvalid_r;
        s(15 downto 12) := pwm_a;
        s(19 downto 16) := pwm_b;
        s(23 downto 20) := pwm_c;
        s(31 downto 24) := pwm_ctrl_i(7 downto 0);
        debug_status_word <= s;
    end process Debug_Status;

    -- Contadores internos de bring-up
    Debug_Counters : process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                data_valid_latch <= '0';
                solver_step_ctr  <= (others => '0');
                carrier_tick_ctr  <= (others => '0');
                timer_tick_ctr    <= (others => '0');
                solver_done_ctr   <= (others => '0');
                solver_clk_alive_ctr <= (others => '0');
            else
                if carrier_tick_s = '1' then
                    carrier_tick_ctr <= carrier_tick_ctr + 1;
                end if;
                if (solver_clk_alive_m2 xor solver_clk_alive_d) = '1' then
                    solver_clk_alive_ctr <= solver_clk_alive_ctr + 1;
                end if;
                timer_tick_ctr  <= timer_tick_ctr_solver;
                solver_done_ctr <= solver_done_ctr_solver;
                if solver_sample_pulse = '1' then
                    data_valid_latch <= '1';
                    solver_step_ctr  <= solver_step_ctr + 1;
                end if;
            end if;
            free_run_ctr <= free_run_ctr + 1;
        end if;
    end process Debug_Counters;

    --------------------------------------------------------------------------
    -- Ratio do decimador: bits[31:3] do pwm_ctrl; 0 = default 77
    -- 77 -> 7.69 MHz / 77 = aproximadamente 100 kHz para o DMA
    -- (bit[2] foi realocado para solver_reset; decim agora tem 29 bits,
    --  ainda muito mais do que o necessário — uso típico < 16 bits.)
    --------------------------------------------------------------------------
    decim_ratio <= resize(unsigned(pwm_ctrl_i(31 downto 3)), 30) when
                   unsigned(pwm_ctrl_i(31 downto 3)) /= 0 else
                   to_unsigned(77, 30);   -- 7.69 MHz / 77 ≈ 100 kHz telemetry

    --------------------------------------------------------------------------
    -- AXI4-Stream com decimador:
    --   Conta pulsos data_valid; a cada decim_ratio pulsos captura uma amostra
    --   e envia ao DMA. Mantém TVALID até DMA confirmar com TREADY, mas não
    --   deixa TVALID preso entre amostras; caso contrário o DMA duplica o
    --   mesmo frame em todos os ciclos com TREADY=1.
    --------------------------------------------------------------------------
    AXI_Stream_Reg : process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                axis_tvalid_r <= '0';
                axis_tlast_r  <= '0';
                axis_tdata_r  <= (others => '0');
                axis_frame_cnt <= (others => '0');
                decim_count   <= (others => '0');
            else
                if m_axis_tready = '1' and axis_tvalid_r = '1' then
                    axis_tvalid_r <= '0';
                    axis_tlast_r  <= '0';
                end if;

                if solver_sample_pulse = '1' then
                    if decim_count >= decim_ratio - 1 then
                        if axis_tvalid_r = '0' or m_axis_tready = '1' then
                            decim_count <= (others => '0');
                            axis_tdata_r( 41 downto   0) <= ialpha_aa_axi;
                            axis_tdata_r( 83 downto  42) <= ibeta_aa_axi;
                            axis_tdata_r(125 downto  84) <= flux_alpha_aa_axi;
                            axis_tdata_r(167 downto 126) <= flux_beta_aa_axi;
                            axis_tdata_r(209 downto 168) <= speed_aa_axi;
                            -- Carry acquisition time with each sample; the PS must not
                            -- reconstruct 128 timestamps from one post-burst GPIO read.
                            axis_tdata_r(241 downto 210) <= std_logic_vector(pwm_cap_time);
                            axis_tdata_r(255 downto 242) <= std_logic_vector(pwm_cap_epoch(13 downto 0));
                            if axis_frame_cnt = to_unsigned(AXIS_DMA_BURST_FRAMES_C - 1,
                                                            axis_frame_cnt'length) then
                                axis_tlast_r   <= '1';
                                axis_frame_cnt <= (others => '0');
                            else
                                axis_tlast_r   <= '0';
                                axis_frame_cnt <= axis_frame_cnt + 1;
                            end if;
                            axis_tvalid_r <= '1';
                        end if;
                    else
                        decim_count <= decim_count + 1;
                    end if;
                end if;
            end if;
        end if;
    end process AXI_Stream_Reg;

    m_axis_tdata  <= axis_tdata_r;
    m_axis_tvalid <= axis_tvalid_r;
    -- AXI DMA S2MM em modo simples espera TLAST no fim do pacote. O PS arma
    -- DMA_BURST_FRAMES frames de 32 bytes; geramos TLAST no ultimo frame.
    m_axis_tlast  <= axis_tlast_r;
    m_axis_tkeep  <= (others => '1');  -- todos os 32 bytes do beat são válidos

End Architecture rtl;
