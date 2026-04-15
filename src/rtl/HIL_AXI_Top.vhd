--! \file       HIL_AXI_Top.vhd
--!
--! \brief      HIL AXI Top — Wrapper PS-controlado para simulação de motor
--!
--!             O PS calcula as referências de tensão (V/F, FOC ou qualquer
--!             algoritmo) e as escreve via AXI GPIO a cada período de portadora.
--!             O PL gera a interrupção (carrier_tick_o → IRQ_F2P), faz a
--!             modulação NPC, converte estados → tensão e roda o TIM_Solver.
--!
--!             FLUXO:
--!               NPCModulator (portadora 1 kHz)
--!                   │ carrier_tick_o ──────────────► IRQ_F2P → PS
--!                   │                                   │ escreve va/vb/vc
--!                   ▼ sample no valley                  ▼
--!               NPCManager (gate states)         AXI GPIO refs
--!                   │
--!               NPC_to_Voltage (±Vdc/2)
--!                   │
--!               TIM_Solver
--!                   │
--!               AXI4-Stream → AXI DMA → DDR
--!
--! MAPA DE REGISTRADORES AXI GPIO (escritas do PS):
--!   axi_gpio_vref_ab  ch1 = va_ref[31:0]   (signed, ±CARRIER_MAX = ±25000)
--!                     ch2 = vb_ref[31:0]
--!   axi_gpio_vref_c   ch1 = vc_ref[31:0]
--!                     ch2 = {decim_ratio[31:2], clear[1], enable[0]}
--!                           decim_ratio=0 → default 375 (10 kHz @ 3.75 MHz solver)
--!   axi_gpio_vdc_torque ch1 = vdc_word[31:0]   (Q31 signed, sign-ext p/ 42b)
--!                       ch2 = torque_word[31:0]
--!
--! SAÍDA AXI4-STREAM (256 bits, 1 beat por amostra):
--!   bits[ 41: 0]  = ialpha
--!   bits[ 83:42]  = ibeta
--!   bits[125:84]  = flux_rotor_alpha
--!   bits[167:126] = flux_rotor_beta
--!   bits[209:168] = speed_mech
--!   bits[255:210] = zeros (padding)
--!
--! \author     Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       13-04-2026
--! \version    2.0
-- =============================================================================

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.BilinearSolverPkg.all;

-- =============================================================================
-- Entity
-- =============================================================================
Entity HIL_AXI_Top is
    Generic (
        -- Clock
        CLK_FREQ         : natural := 150_000_000;   -- FCLK0 da EBAZ4205

        -- Portadora NPC — 1 kHz gera IRQ confortável para Linux sem RT
        -- CARRIER_MAX = CLK_FREQ / PWM_FREQ / 2 = 75000
        -- Referencias do PS devem estar em ±CARRIER_MAX para 100% modulação
        PWM_FREQ         : natural := 1_000;

        -- NPC Modulator
        NPC_DW           : natural := 32;

        -- TIM Solver
        TIM_DW           : natural := 42;
        -- Ts = 40 ciclos a 150 MHz = 266.67 ns
        -- Solver roda livre (free-running), desacoplado do carrier tick do PS
        -- Taxa de saída efetiva = 150 MHz / 40 = 3.75 MHz (antes do decimador)
        DISC_STEP        : real    := 40.0 / 150_000_000.0;

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

        -- ── Referências de tensão (escritas pelo PS na ISR) ──────────────────
        -- Unidade: ±CARRIER_MAX = ±(CLK_FREQ/PWM_FREQ/2)
        -- Ex: CLK=50MHz, PWM=1kHz → CARRIER_MAX=25000
        -- 100% modulação = ±25000; 85% = ±21250
        va_ref_i         : in  std_logic_vector(NPC_DW-1 downto 0);
        vb_ref_i         : in  std_logic_vector(NPC_DW-1 downto 0);
        vc_ref_i         : in  std_logic_vector(NPC_DW-1 downto 0);

        -- ── Controle PWM (bit[0]=enable, bit[1]=clear_fault) ─────────────────
        pwm_ctrl_i       : in  std_logic_vector(31 downto 0);

        -- ── Barramento DC e torque de carga (Q31 signed → 42b) ───────────────
        vdc_word_i       : in  std_logic_vector(31 downto 0);
        torque_word_i    : in  std_logic_vector(31 downto 0);

        -- ── Interrupção para o PS (1 pulso por período de portadora) ─────────
        -- Conectar a IRQ_F2P[0] no Block Design
        carrier_tick_o   : out std_logic;

        -- ── Monitoramento (32 MSBs de cada saída de 42 bits) ─────────────────
        ialpha_mon_o     : out std_logic_vector(31 downto 0);
        ibeta_mon_o      : out std_logic_vector(31 downto 0);
        flux_alpha_mon_o : out std_logic_vector(31 downto 0);
        flux_beta_mon_o  : out std_logic_vector(31 downto 0);
        speed_mon_o      : out std_logic_vector(31 downto 0);
        data_valid_mon_o : out std_logic;

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
    constant NPC_STATE_POS  : std_logic_vector(3 downto 0) := "0011";  -- +Vdc/2
    constant NPC_STATE_NEG  : std_logic_vector(3 downto 0) := "1100";  -- -Vdc/2

    --------------------------------------------------------------------------
    -- Controle
    --------------------------------------------------------------------------
    signal pwm_enable_s  : std_logic;
    signal pwm_clear_s   : std_logic;

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

    --------------------------------------------------------------------------
    -- Tensões de fase para o solver (42 bits)
    --------------------------------------------------------------------------
    signal va_motor      : std_logic_vector(TIM_DW-1 downto 0);
    signal vb_motor      : std_logic_vector(TIM_DW-1 downto 0);
    signal vc_motor      : std_logic_vector(TIM_DW-1 downto 0);

    --------------------------------------------------------------------------
    -- Saídas do TIM_Solver
    --------------------------------------------------------------------------
    signal ialpha_s      : std_logic_vector(TIM_DW-1 downto 0);
    signal ibeta_s       : std_logic_vector(TIM_DW-1 downto 0);
    signal flux_alpha_s  : std_logic_vector(TIM_DW-1 downto 0);
    signal flux_beta_s   : std_logic_vector(TIM_DW-1 downto 0);
    signal speed_s       : std_logic_vector(TIM_DW-1 downto 0);
    signal data_valid_s  : std_logic;

    --------------------------------------------------------------------------
    -- Registrador AXI4-Stream + Decimador
    --------------------------------------------------------------------------
    signal axis_tdata_r   : std_logic_vector(255 downto 0);
    signal axis_tvalid_r  : std_logic;
    signal decim_count    : unsigned(29 downto 0);
    signal decim_ratio    : unsigned(29 downto 0);

Begin

    --------------------------------------------------------------------------
    -- Desempacotamento do controle PWM
    --------------------------------------------------------------------------
    pwm_enable_s <= pwm_ctrl_i(0);
    pwm_clear_s  <= pwm_ctrl_i(1);

    --------------------------------------------------------------------------
    -- Extensão de sinal: 32 → 42 bits (Q31 → Q42, mantém escala)
    --------------------------------------------------------------------------
    vdc_bus_42 <= resize(signed(vdc_word_i),   TIM_DW);
    torque_42  <= std_logic_vector(resize(signed(torque_word_i), TIM_DW));

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
        -- Referências escritas pelo PS via AXI GPIO
        va_ref_i        => va_ref_i,
        vb_ref_i        => vb_ref_i,
        vc_ref_i        => vc_ref_i,
        -- Tick de portadora → IRQ para o PS
        carrier_tick_o  => carrier_tick_o,
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
    -- NPC_to_Voltage — converte estado de gate em tensão para o solver
    --   "0011" (POS) → +Vdc/2
    --   "1100" (NEG) → -Vdc/2
    --   outros       → 0 V (estado zero / desligado)
    --------------------------------------------------------------------------
    NPC_to_Voltage : process(pwm_a, pwm_b, pwm_c, vdc_pos, vdc_neg)
    begin
        case pwm_a is
            when NPC_STATE_POS => va_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_NEG => va_motor <= std_logic_vector(vdc_neg);
            when others        => va_motor <= (others => '0');
        end case;

        case pwm_b is
            when NPC_STATE_POS => vb_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_NEG => vb_motor <= std_logic_vector(vdc_neg);
            when others        => vb_motor <= (others => '0');
        end case;

        case pwm_c is
            when NPC_STATE_POS => vc_motor <= std_logic_vector(vdc_pos);
            when NPC_STATE_NEG => vc_motor <= std_logic_vector(vdc_neg);
            when others        => vc_motor <= (others => '0');
        end case;
    end process NPC_to_Voltage;

    --------------------------------------------------------------------------
    -- TIM_Solver — modelo de motor de indução trifásico
    --------------------------------------------------------------------------
    TIM_Solver_Inst : entity work.TIM_Solver
    generic map (
        DATA_WIDTH       => TIM_DW,
        CLOCK_FREQUENCY  => CLK_FREQ,
        Ts               => DISC_STEP,
        rs               => MOTOR_RS,
        rr               => MOTOR_RR,
        ls               => MOTOR_LS,
        lr               => MOTOR_LR,
        lm               => MOTOR_LM,
        j                => MOTOR_J,
        npp              => MOTOR_NPP
    )
    port map (
        sysclk              => clk,
        reset_n             => rst_n,
        va_i                => va_motor,
        vb_i                => vb_motor,
        vc_i                => vc_motor,
        torque_load_i       => torque_42,
        ialpha_o            => ialpha_s,
        ibeta_o             => ibeta_s,
        flux_rotor_alpha_o  => flux_alpha_s,
        flux_rotor_beta_o   => flux_beta_s,
        speed_mech_o        => speed_s,
        data_valid_o        => data_valid_s
    );

    --------------------------------------------------------------------------
    -- Monitoramento: 32 MSBs de cada saída de 42 bits
    --------------------------------------------------------------------------
    ialpha_mon_o     <= ialpha_s(TIM_DW-1 downto TIM_DW-32);
    ibeta_mon_o      <= ibeta_s(TIM_DW-1 downto TIM_DW-32);
    flux_alpha_mon_o <= flux_alpha_s(TIM_DW-1 downto TIM_DW-32);
    flux_beta_mon_o  <= flux_beta_s(TIM_DW-1 downto TIM_DW-32);
    speed_mon_o      <= speed_s(TIM_DW-1 downto TIM_DW-32);
    data_valid_mon_o <= data_valid_s;

    --------------------------------------------------------------------------
    -- Ratio do decimador: bits[31:2] do pwm_ctrl; 0 = default 375
    -- 375 → 3.75 MHz / 375 = 10 kHz de saída para o DMA
    --------------------------------------------------------------------------
    decim_ratio <= unsigned(pwm_ctrl_i(31 downto 2)) when
                   unsigned(pwm_ctrl_i(31 downto 2)) /= 0 else
                   to_unsigned(375, 30);

    --------------------------------------------------------------------------
    -- AXI4-Stream com decimador:
    --   Conta pulsos data_valid; a cada decim_ratio pulsos captura uma amostra
    --   e envia ao DMA. Mantém TVALID até DMA confirmar com TREADY.
    --------------------------------------------------------------------------
    AXI_Stream_Reg : process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                axis_tvalid_r <= '0';
                axis_tdata_r  <= (others => '0');
                decim_count   <= (others => '0');
            elsif data_valid_s = '1' then
                if decim_count >= decim_ratio - 1 then
                    decim_count <= (others => '0');
                    axis_tdata_r( 41 downto   0) <= ialpha_s;
                    axis_tdata_r( 83 downto  42) <= ibeta_s;
                    axis_tdata_r(125 downto  84) <= flux_alpha_s;
                    axis_tdata_r(167 downto 126) <= flux_beta_s;
                    axis_tdata_r(209 downto 168) <= speed_s;
                    axis_tdata_r(255 downto 210) <= (others => '0');
                    axis_tvalid_r <= '1';
                else
                    decim_count <= decim_count + 1;
                end if;
            elsif m_axis_tready = '1' and axis_tvalid_r = '1' then
                axis_tvalid_r <= '0';
            end if;
        end if;
    end process AXI_Stream_Reg;

    m_axis_tdata  <= axis_tdata_r;
    m_axis_tvalid <= axis_tvalid_r;
    -- TLAST = '0': DMA modo simples termina quando LENGTH bytes chegarem.
    -- Se TLAST fosse TVALID, o DMA pararia após cada amostra de 32 bytes
    -- e exigiria re-armamento constante pelo PS.
    m_axis_tlast  <= '0';
    m_axis_tkeep  <= (others => '1');  -- todos os 32 bytes do beat são válidos

End Architecture rtl;
