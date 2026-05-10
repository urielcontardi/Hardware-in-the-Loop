-- HIL_Regs_AXI.vhd
--
-- AXI4-Lite slave — 6 write registers for HIL PS→PL control path.
-- Written in user VHDL (not Xilinx IP), so Vivado's optimizer cannot
-- constant-propagate through it: PS7 is a hard-IP black box, making
-- the register values non-constant by definition.
--
-- Register map (byte offsets from base):
--   0x00  va_ref      signed int32, ±CARRIER_MAX
--   0x04  vb_ref
--   0x08  vc_ref
--   0x0C  pwm_ctrl    bit0=enable, bit1=clear_fault, [31:2]=decim_ratio
--   0x10  vdc_word    Q18.14 signed (V)
--   0x14  torque_word Q18.14 signed (N·m)
--   0x18  debug_magic  read-only, fixed 0x48494C52 ("HILR")
--   0x1C  debug0       read-only, external debug bus from HIL_AXI_Top

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity HIL_Regs_AXI is
    generic (
        C_S_AXI_DATA_WIDTH : integer := 32;
        C_S_AXI_ADDR_WIDTH : integer := 5   -- covers 0x00..0x1F (6 regs)
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

        -- Read-only debug input sampled through this known-good AXI slave.
        debug0_i      : in  std_logic_vector(31 downto 0)
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
    signal reg_pwm_ctrl    : std_logic_vector(31 downto 0) := (others => '0');
    signal reg_vdc_word    : std_logic_vector(31 downto 0) := (others => '0');
    signal reg_torque_word : std_logic_vector(31 downto 0) := (others => '0');

    constant DEBUG_MAGIC : std_logic_vector(31 downto 0) := x"48494C52"; -- "HILR"

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
    attribute dont_touch of va_ref_o        : signal is "true";
    attribute dont_touch of vb_ref_o        : signal is "true";
    attribute dont_touch of vc_ref_o        : signal is "true";
    attribute dont_touch of pwm_ctrl_o      : signal is "true";
    attribute dont_touch of vdc_word_o      : signal is "true";
    attribute dont_touch of torque_word_o   : signal is "true";

begin

    -- Drive outputs directly from registers
    va_ref_o      <= reg_va_ref;
    vb_ref_o      <= reg_vb_ref;
    vc_ref_o      <= reg_vc_ref;
    pwm_ctrl_o    <= reg_pwm_ctrl;
    vdc_word_o    <= reg_vdc_word;
    torque_word_o <= reg_torque_word;

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
                reg_pwm_ctrl    <= (others => '0');
                reg_vdc_word    <= (others => '0');
                reg_torque_word <= (others => '0');
            else
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
                    case aw_addr(4 downto 2) is
                        when "000" => reg_va_ref      <= S_AXI_WDATA;
                        when "001" => reg_vb_ref      <= S_AXI_WDATA;
                        when "010" => reg_vc_ref      <= S_AXI_WDATA;
                        when "011" => reg_pwm_ctrl    <= S_AXI_WDATA;
                        when "100" => reg_vdc_word    <= S_AXI_WDATA;
                        when "101" => reg_torque_word <= S_AXI_WDATA;
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
                    case S_AXI_ARADDR(4 downto 2) is
                        when "000" => rdata <= reg_va_ref;
                        when "001" => rdata <= reg_vb_ref;
                        when "010" => rdata <= reg_vc_ref;
                        when "011" => rdata <= reg_pwm_ctrl;
                        when "100" => rdata <= reg_vdc_word;
                        when "101" => rdata <= reg_torque_word;
                        when "110" => rdata <= DEBUG_MAGIC;
                        when "111" => rdata <= debug0_i;
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
