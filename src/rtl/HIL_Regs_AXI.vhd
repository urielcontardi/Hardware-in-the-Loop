-- HIL_Regs_AXI.vhd
--
-- AXI4-Lite slave — control/debug regs for HIL.
-- Written in user VHDL (not Xilinx IP), so Vivado's optimizer cannot
-- constant-propagate through it: PS7 is a hard-IP black box, making
-- the register values non-constant by definition.
--
-- Register map (byte offsets from base):
--   0x00  va_ref           write — signed int32, ±CARRIER_MAX
--   0x04  vb_ref           write
--   0x08  vc_ref           write
--   0x0C  pwm_ctrl         write — bit0=enable, bit1=clear_fault,
--                                   bit2=solver_reset (1=hold solver in reset),
--                                   [31:3]=decim ratio
--   0x10  vdc_word         write — Q18.14 signed (V)
--   0x14  torque_word      write — Q18.14 signed (N·m)
--   0x18  DEBUG_MAGIC      read  — 0x48494C52 ("HILR"), prova bitstream certo
--   0x1C  debug_status     read  — bitfield: rst_n, enable, busy, done, ...
--   0x20  free_run_ctr     read  — clock vivo (incrementa todo ciclo)
--   0x24  carrier_tick_ctr read  — ticks do NPC carrier
--   0x28  timer_tick_ctr   read  — ticks do timer do TIM_Solver
--   0x2C  data_valid_latch read  — bit[0]=1 indica solver produziu saída
--   0x30  coeff_addr       write/read — [1:0]=matrix A/B/Y, [4:2]=row, [7:5]=col
--   0x34  coeff_data_lo    write/read — coefficient[31:0] raw Q14.28
--   0x38  coeff_data_hi    write/read — coefficient[41:32]
--   0x3C  coeff_commit     write      — bit[0]=1 pulses coeff_we_o,
--                                      bit[1]=1 pulses coeff_apply_o
--   0x40  pwm_cap_ctrl     write      — bit0=start, bit1=stop, bit2=clear
--   0x44  pwm_cap_status   read       — capture status/count
--   0x48  pwm_cap_window   write/read — cycles; 0=continuous while enabled
--   0x4C  pwm_cap_data_lo  read       — current event[31:0]
--   0x50  pwm_cap_data_hi  read       — current event[63:32]
--   0x54  pwm_cap_pop      write      — bit0 pops current event
--   0x58  hil_time          read       — current run-local time[31:0]
--   0x5C  hil_epoch         read       — current run epoch[15:0]

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity HIL_Regs_AXI is
    generic (
        C_S_AXI_DATA_WIDTH : integer := 32;
        C_S_AXI_ADDR_WIDTH : integer := 8   -- covers 0x00..0xFF
    );
    port (
        -- AXI4-Lite slave interface
        S_AXI_ACLK    : in  std_logic;
        S_AXI_ARESETN : in  std_logic;

        S_AXI_AWADDR  : in  std_logic_vector(C_S_AXI_ADDR_WIDTH-1 downto 0);
        S_AXI_AWVALID : in  std_logic;
        S_AXI_AWREADY : out std_logic;

        S_AXI_WDATA   : in  std_logic_vector(C_S_AXI_DATA_WIDTH-1 downto 0);
        S_AXI_WSTRB   : in  std_logic_vector((C_S_AXI_DATA_WIDTH/8)-1 downto 0);
        S_AXI_WVALID  : in  std_logic;
        S_AXI_WREADY  : out std_logic;

        S_AXI_BRESP   : out std_logic_vector(1 downto 0);
        S_AXI_BVALID  : out std_logic;
        S_AXI_BREADY  : in  std_logic;

        S_AXI_ARADDR  : in  std_logic_vector(C_S_AXI_ADDR_WIDTH-1 downto 0);
        S_AXI_ARVALID : in  std_logic;
        S_AXI_ARREADY : out std_logic;

        S_AXI_RDATA   : out std_logic_vector(C_S_AXI_DATA_WIDTH-1 downto 0);
        S_AXI_RRESP   : out std_logic_vector(1 downto 0);
        S_AXI_RVALID  : out std_logic;
        S_AXI_RREADY  : in  std_logic;

        -- Register outputs → HIL_AXI_Top
        va_ref_o      : out std_logic_vector(31 downto 0);
        vb_ref_o      : out std_logic_vector(31 downto 0);
        vc_ref_o      : out std_logic_vector(31 downto 0);
        pwm_ctrl_o    : out std_logic_vector(31 downto 0);
        vdc_word_o    : out std_logic_vector(31 downto 0);
        torque_word_o : out std_logic_vector(31 downto 0);

        -- Runtime solver coefficient write port.
        coeff_we_o     : out std_logic;
        coeff_apply_o  : out std_logic;
        coeff_addr_o   : out std_logic_vector(31 downto 0);
        coeff_data_o   : out std_logic_vector(41 downto 0);

        -- PWM transition capture control/readout.
        pwm_cap_start_o  : out std_logic;
        pwm_cap_stop_o   : out std_logic;
        pwm_cap_clear_o  : out std_logic;
        pwm_cap_pop_o    : out std_logic;
        pwm_cap_window_o : out std_logic_vector(31 downto 0);
        pwm_cap_status_i : in  std_logic_vector(31 downto 0);
        pwm_cap_data_i   : in  std_logic_vector(63 downto 0);
        hil_time_i       : in  std_logic_vector(31 downto 0);
        hil_epoch_i      : in  std_logic_vector(31 downto 0);

        -- Read-only debug bus from HIL_AXI_Top.
        dbg_status_i     : in  std_logic_vector(31 downto 0);
        dbg_free_run_i   : in  std_logic_vector(31 downto 0);
        dbg_carrier_i    : in  std_logic_vector(31 downto 0);
        dbg_timer_i      : in  std_logic_vector(31 downto 0);
        dbg_dv_latch_i   : in  std_logic_vector(31 downto 0)
    );
end entity;

architecture rtl of HIL_Regs_AXI is

    signal awready : std_logic := '0';
    signal wready  : std_logic := '0';
    signal bvalid  : std_logic := '0';
    signal arready : std_logic := '0';
    signal rvalid  : std_logic := '0';
    signal rdata   : std_logic_vector(31 downto 0) := (others => '0');

    -- Latched write address
    signal aw_addr : std_logic_vector(C_S_AXI_ADDR_WIDTH-1 downto 0);

    -- The 6 control registers
    signal reg_va_ref      : std_logic_vector(31 downto 0) := (others => '0');
    signal reg_vb_ref      : std_logic_vector(31 downto 0) := (others => '0');
    signal reg_vc_ref      : std_logic_vector(31 downto 0) := (others => '0');
    signal shadow_va_ref   : std_logic_vector(31 downto 0) := (others => '0');
    signal shadow_vb_ref   : std_logic_vector(31 downto 0) := (others => '0');
    signal shadow_vc_ref   : std_logic_vector(31 downto 0) := (others => '0');
    signal reg_pwm_ctrl    : std_logic_vector(31 downto 0) := (others => '0');
    signal reg_vdc_word    : std_logic_vector(31 downto 0) := (others => '0');
    signal reg_torque_word : std_logic_vector(31 downto 0) := (others => '0');
    signal reg_coeff_addr  : std_logic_vector(31 downto 0) := (others => '0');
    signal reg_coeff_lo    : std_logic_vector(31 downto 0) := (others => '0');
    signal reg_coeff_hi    : std_logic_vector(31 downto 0) := (others => '0');
    signal reg_pwm_cap_window : std_logic_vector(31 downto 0) := (others => '0');
    signal coeff_we_r      : std_logic := '0';
    signal coeff_apply_r   : std_logic := '0';
    signal pwm_cap_start_r : std_logic := '0';
    signal pwm_cap_stop_r  : std_logic := '0';
    signal pwm_cap_clear_r : std_logic := '0';
    signal pwm_cap_pop_r   : std_logic := '0';

    constant DEBUG_MAGIC : std_logic_vector(31 downto 0) := x"48494C52"; -- "HILR"
    constant PWM_CAP_CTRL_MAGIC : std_logic_vector(31 downto 0) := x"FFFF0100";
    constant PWM_CAP_POP_MAGIC  : std_logic_vector(31 downto 0) := x"FFFF0104";

    -- Prevent Vivado from trimming output port connections via dead-cone elimination.
    -- Without these attributes, synthesis sees the registers as "only driving
    -- logic that produces constant 0 outputs" and eliminates the output ports.
    attribute dont_touch : string;
    attribute dont_touch of reg_va_ref      : signal is "true";
    attribute dont_touch of reg_vb_ref      : signal is "true";
    attribute dont_touch of reg_vc_ref      : signal is "true";
    attribute dont_touch of reg_pwm_ctrl    : signal is "true";
    attribute dont_touch of reg_vdc_word    : signal is "true";
    attribute dont_touch of reg_torque_word : signal is "true";
    attribute dont_touch of reg_coeff_addr  : signal is "true";
    attribute dont_touch of reg_coeff_lo    : signal is "true";
    attribute dont_touch of reg_coeff_hi    : signal is "true";
    attribute dont_touch of reg_pwm_cap_window : signal is "true";

begin

    -- Drive outputs directly from registers
    va_ref_o      <= reg_va_ref;
    vb_ref_o      <= reg_vb_ref;
    vc_ref_o      <= reg_vc_ref;
    pwm_ctrl_o    <= reg_pwm_ctrl;
    vdc_word_o    <= reg_vdc_word;
    torque_word_o <= reg_torque_word;
    coeff_we_o     <= coeff_we_r;
    coeff_apply_o  <= coeff_apply_r;
    coeff_addr_o   <= reg_coeff_addr;
    coeff_data_o   <= reg_coeff_hi(9 downto 0) & reg_coeff_lo;
    pwm_cap_start_o  <= pwm_cap_start_r;
    pwm_cap_stop_o   <= pwm_cap_stop_r;
    pwm_cap_clear_o  <= pwm_cap_clear_r;
    pwm_cap_pop_o    <= pwm_cap_pop_r;
    pwm_cap_window_o <= reg_pwm_cap_window;

    S_AXI_AWREADY <= awready;
    S_AXI_WREADY  <= wready;
    S_AXI_BRESP   <= "00";
    S_AXI_BVALID  <= bvalid;
    S_AXI_ARREADY <= arready;
    S_AXI_RDATA   <= rdata;
    S_AXI_RRESP   <= "00";
    S_AXI_RVALID  <= rvalid;

    -- Write channel
    write_proc : process(S_AXI_ACLK)
    begin
        if rising_edge(S_AXI_ACLK) then
            if S_AXI_ARESETN = '0' then
                awready      <= '0';
                wready       <= '0';
                bvalid       <= '0';
                reg_va_ref      <= (others => '0');
                reg_vb_ref      <= (others => '0');
                reg_vc_ref      <= (others => '0');
                shadow_va_ref   <= (others => '0');
                shadow_vb_ref   <= (others => '0');
                shadow_vc_ref   <= (others => '0');
                reg_pwm_ctrl    <= (others => '0');
                reg_vdc_word    <= (others => '0');
                reg_torque_word <= (others => '0');
                reg_coeff_addr  <= (others => '0');
                reg_coeff_lo    <= (others => '0');
                reg_coeff_hi    <= (others => '0');
                reg_pwm_cap_window <= (others => '0');
                coeff_we_r      <= '0';
                coeff_apply_r   <= '0';
                pwm_cap_start_r <= '0';
                pwm_cap_stop_r  <= '0';
                pwm_cap_clear_r <= '0';
                pwm_cap_pop_r   <= '0';
            else
                coeff_we_r <= '0';
                coeff_apply_r <= '0';
                pwm_cap_start_r <= '0';
                pwm_cap_stop_r  <= '0';
                pwm_cap_clear_r <= '0';
                pwm_cap_pop_r   <= '0';

                -- AWREADY: accept address
                if awready = '0' and S_AXI_AWVALID = '1' then
                    awready <= '1';
                    aw_addr <= S_AXI_AWADDR;
                else
                    awready <= '0';
                end if;

                -- WREADY: accept data
                if wready = '0' and S_AXI_WVALID = '1' then
                    wready <= '1';
                else
                    wready <= '0';
                end if;

                -- Write to register when both address and data are valid
                if awready = '1' and S_AXI_AWVALID = '1' and
                   wready  = '1' and S_AXI_WVALID  = '1' then
                    case to_integer(unsigned(aw_addr(7 downto 2))) is
                        -- Stage the three phases independently. pwm_ctrl is
                        -- written last by gpio_set_pwm_ctrl and atomically
                        -- commits the complete triplet to the modulator.
                        when 0  => shadow_va_ref   <= S_AXI_WDATA;
                        when 1  => shadow_vb_ref   <= S_AXI_WDATA;
                        when 2  => shadow_vc_ref   <= S_AXI_WDATA;
                        when 3  =>
                            reg_va_ref   <= shadow_va_ref;
                            reg_vb_ref   <= shadow_vb_ref;
                            reg_vc_ref   <= shadow_vc_ref;
                            reg_pwm_ctrl <= S_AXI_WDATA;
                        when 4  => reg_vdc_word    <= S_AXI_WDATA;
                        when 5  => reg_torque_word <= S_AXI_WDATA;
                        when 12 => reg_coeff_addr  <= S_AXI_WDATA;
                        when 13 => reg_coeff_lo    <= S_AXI_WDATA;
                        when 14 => reg_coeff_hi    <= S_AXI_WDATA;
                        when 15 =>
                            coeff_we_r    <= S_AXI_WDATA(0);
                            coeff_apply_r <= S_AXI_WDATA(1);
                        when 16 =>
                            pwm_cap_start_r <= S_AXI_WDATA(0);
                            pwm_cap_stop_r  <= S_AXI_WDATA(1);
                            pwm_cap_clear_r <= S_AXI_WDATA(2);
                            reg_coeff_addr  <= PWM_CAP_CTRL_MAGIC;
                            reg_coeff_lo    <= S_AXI_WDATA;
                            reg_coeff_hi    <= (others => '0');
                            coeff_we_r      <= '1';
                        when 18 => reg_pwm_cap_window <= S_AXI_WDATA;
                        when 21 =>
                            pwm_cap_pop_r  <= S_AXI_WDATA(0);
                            reg_coeff_addr <= PWM_CAP_POP_MAGIC;
                            reg_coeff_lo   <= S_AXI_WDATA;
                            reg_coeff_hi   <= (others => '0');
                            coeff_we_r     <= '1';
                        when others => null;
                    end case;
                    bvalid <= '1';
                elsif bvalid = '1' and S_AXI_BREADY = '1' then
                    bvalid <= '0';
                end if;
            end if;
        end if;
    end process;

    -- Read channel (PS can read back register values)
    read_proc : process(S_AXI_ACLK)
    begin
        if rising_edge(S_AXI_ACLK) then
            if S_AXI_ARESETN = '0' then
                arready <= '0';
                rvalid  <= '0';
                rdata   <= (others => '0');
            else
                if arready = '0' and S_AXI_ARVALID = '1' then
                    arready <= '1';
                    case to_integer(unsigned(S_AXI_ARADDR(7 downto 2))) is
                        when 0  => rdata <= shadow_va_ref;
                        when 1  => rdata <= shadow_vb_ref;
                        when 2  => rdata <= shadow_vc_ref;
                        when 3  => rdata <= reg_pwm_ctrl;
                        when 4  => rdata <= reg_vdc_word;
                        when 5  => rdata <= reg_torque_word;
                        when 6  => rdata <= DEBUG_MAGIC;
                        when 7  => rdata <= dbg_status_i;
                        when 8  => rdata <= dbg_free_run_i;
                        when 9  => rdata <= dbg_carrier_i;
                        when 10 => rdata <= dbg_timer_i;
                        when 11 => rdata <= dbg_dv_latch_i;
                        when 12 => rdata <= reg_coeff_addr;
                        when 13 => rdata <= reg_coeff_lo;
                        when 14 => rdata <= reg_coeff_hi;
                        when 15 => rdata <= (others => '0');
                        when 17 => rdata <= dbg_status_i;
                        when 18 => rdata <= reg_pwm_cap_window;
                        when 19 => rdata <= dbg_free_run_i;
                        when 20 => rdata <= dbg_carrier_i;
                        when 22 => rdata <= dbg_timer_i;
                        when 23 => rdata <= dbg_dv_latch_i;
                        when others => rdata <= (others => '0');
                    end case;
                    rvalid <= '1';
                else
                    arready <= '0';
                    if rvalid = '1' and S_AXI_RREADY = '1' then
                        rvalid <= '0';
                    end if;
                end if;
            end if;
        end if;
    end process;

end architecture;
