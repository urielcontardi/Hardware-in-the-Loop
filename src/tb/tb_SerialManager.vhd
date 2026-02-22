--! \file       tb_SerialManager.vhd
--!
--! \brief      Testbench for SerialManager module.
--!             Tests Write, Read, and Read All commands over UART.
--!
--! \author     Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       16-02-2026

--------------------------------------------------------------------------
-- Default libraries
--------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

--------------------------------------------------------------------------
-- Entity (empty for testbench)
--------------------------------------------------------------------------
entity tb_SerialManager is
end entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
architecture sim of tb_SerialManager is

    --------------------------------------------------------------------------
    -- Constants
    --------------------------------------------------------------------------
    constant CLK_FREQ       : natural := 100_000_000;
    constant BAUD_RATE      : natural := 1_000_000;
    constant DATA_WIDTH     : natural := 42;
    constant CLK_PERIOD     : time    := 10 ns;
    constant BIT_PERIOD     : time    := 1 us;
    constant BYTES_PER_WORD : natural := (DATA_WIDTH + 7) / 8;  -- 6
    constant RECV_TIMEOUT   : time    := BIT_PERIOD * 200;      -- 200 bit periods

    --------------------------------------------------------------------------
    -- DUT Signals
    --------------------------------------------------------------------------
    signal clk_i            : std_logic := '0';
    signal reset_n_i        : std_logic := '0';
    signal rx_i             : std_logic := '1';
    signal tx_o             : std_logic;

    signal vdc_bus_o        : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal torque_load_o    : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal config_valid_o   : std_logic;

    signal va_motor_i       : std_logic_vector(DATA_WIDTH-1 downto 0) := (others => '0');
    signal vb_motor_i       : std_logic_vector(DATA_WIDTH-1 downto 0) := (others => '0');
    signal vc_motor_i       : std_logic_vector(DATA_WIDTH-1 downto 0) := (others => '0');
    signal ialpha_i         : std_logic_vector(DATA_WIDTH-1 downto 0) := (others => '0');
    signal ibeta_i          : std_logic_vector(DATA_WIDTH-1 downto 0) := (others => '0');
    signal flux_alpha_i     : std_logic_vector(DATA_WIDTH-1 downto 0) := (others => '0');
    signal flux_beta_i      : std_logic_vector(DATA_WIDTH-1 downto 0) := (others => '0');
    signal speed_mech_i     : std_logic_vector(DATA_WIDTH-1 downto 0) := (others => '0');
    signal data_valid_i     : std_logic := '0';

    signal sim_done         : boolean := false;

    --------------------------------------------------------------------------
    -- Procedure: Send one byte over UART (drive rx_i)
    --------------------------------------------------------------------------
    procedure uart_send_byte (
        signal   rx : out std_logic;
        constant d  : in  std_logic_vector(7 downto 0)
    ) is
    begin
        rx <= '0';
        wait for BIT_PERIOD;
        for i in 0 to 7 loop
            rx <= d(i);
            wait for BIT_PERIOD;
        end loop;
        rx <= '1';
        wait for BIT_PERIOD;
    end procedure;

    --------------------------------------------------------------------------
    -- Procedure: Receive one byte from UART (sample tx_o)
    -- Returns false in 'ok' if timed out
    --------------------------------------------------------------------------
    procedure uart_recv_byte (
        signal   tx   : in  std_logic;
        variable d    : out std_logic_vector(7 downto 0);
        variable ok   : out boolean
    ) is
    begin
        ok := true;
        -- Wait for start bit (falling edge: tx transitions to '0').
        -- Using 'wait until' ensures we wait for an EVENT where tx
        -- becomes '0'. If tx is already '0' (mid-byte), this waits
        -- for the NEXT transition to '0', preventing misaligned sampling.
        wait until tx = '0' for RECV_TIMEOUT;
        if tx /= '0' then
            report "TIMEOUT: No start bit detected within " &
                   time'image(RECV_TIMEOUT) severity error;
            d := (others => '0');
            ok := false;
            return;
        end if;
        -- We detected start bit edge. Wait to center of first data bit.
        wait for BIT_PERIOD / 2;
        -- Sample 8 data bits (LSB first)
        for i in 0 to 7 loop
            wait for BIT_PERIOD;
            d(i) := tx;
        end loop;
        -- Wait through stop bit
        wait for BIT_PERIOD;
    end procedure;

    --------------------------------------------------------------------------
    -- Procedure: Send Write command
    --------------------------------------------------------------------------
    procedure uart_write_reg (
        signal   rx   : out std_logic;
        constant addr : in  natural;
        constant val  : in  std_logic_vector(47 downto 0)
    ) is
    begin
        uart_send_byte(rx, x"57");
        uart_send_byte(rx, std_logic_vector(to_unsigned(addr, 8)));
        for i in BYTES_PER_WORD-1 downto 0 loop
            uart_send_byte(rx, val(i*8+7 downto i*8));
        end loop;
    end procedure;

    --------------------------------------------------------------------------
    -- Procedure: Send Read command and capture response
    --------------------------------------------------------------------------
    procedure uart_read_reg (
        signal   rx      : out std_logic;
        signal   tx      : in  std_logic;
        constant addr    : in  natural;
        variable hdr     : out std_logic_vector(7 downto 0);
        variable rd_addr : out std_logic_vector(7 downto 0);
        variable rd_val  : out std_logic_vector(47 downto 0);
        variable success : out boolean
    ) is
        variable byte_tmp : std_logic_vector(7 downto 0);
        variable ok       : boolean;
    begin
        success := true;
        uart_send_byte(rx, x"52");
        uart_send_byte(rx, std_logic_vector(to_unsigned(addr, 8)));
        -- Receive response (uart_recv_byte waits for start bit automatically)
        uart_recv_byte(tx, hdr, ok);
        if not ok then success := false; return; end if;
        uart_recv_byte(tx, rd_addr, ok);
        if not ok then success := false; return; end if;
        rd_val := (others => '0');
        for i in BYTES_PER_WORD-1 downto 0 loop
            uart_recv_byte(tx, byte_tmp, ok);
            if not ok then success := false; return; end if;
            rd_val(i*8+7 downto i*8) := byte_tmp;
        end loop;
    end procedure;

begin

    --------------------------------------------------------------------------
    -- Clock generation
    --------------------------------------------------------------------------
    clk_i <= not clk_i after CLK_PERIOD / 2 when not sim_done else '0';

    --------------------------------------------------------------------------
    -- DUT Instantiation
    --------------------------------------------------------------------------
    DUT : entity work.SerialManager
    generic map (
        CLK_FREQ   => CLK_FREQ,
        BAUD_RATE  => BAUD_RATE,
        DATA_WIDTH => DATA_WIDTH
    )
    port map (
        clk_i          => clk_i,
        reset_n_i      => reset_n_i,
        rx_i           => rx_i,
        tx_o           => tx_o,
        vdc_bus_o      => vdc_bus_o,
        torque_load_o  => torque_load_o,
        config_valid_o => config_valid_o,
        va_motor_i     => va_motor_i,
        vb_motor_i     => vb_motor_i,
        vc_motor_i     => vc_motor_i,
        ialpha_i       => ialpha_i,
        ibeta_i        => ibeta_i,
        flux_alpha_i   => flux_alpha_i,
        flux_beta_i    => flux_beta_i,
        speed_mech_i   => speed_mech_i,
        data_valid_i   => data_valid_i
    );

    --------------------------------------------------------------------------
    -- Stimulus Process
    --------------------------------------------------------------------------
    Stim_Proc : process
        variable hdr_v     : std_logic_vector(7 downto 0);
        variable addr_v    : std_logic_vector(7 downto 0);
        variable data_v    : std_logic_vector(47 downto 0);
        variable byte_tmp  : std_logic_vector(7 downto 0);
        variable ok_v      : boolean;
        constant VDC_VAL   : std_logic_vector(47 downto 0) := x"00000000ABCD";
        constant TOR_VAL   : std_logic_vector(47 downto 0) := x"000000001234";
    begin
        -------------------------------------------------------
        -- Reset
        -------------------------------------------------------
        reset_n_i <= '0';
        wait for CLK_PERIOD * 10;
        reset_n_i <= '1';
        wait for CLK_PERIOD * 5;

        -- Set monitor input values
        va_motor_i   <= std_logic_vector(to_signed(100, DATA_WIDTH));
        vb_motor_i   <= std_logic_vector(to_signed(-50, DATA_WIDTH));
        vc_motor_i   <= std_logic_vector(to_signed(25,  DATA_WIDTH));
        ialpha_i     <= std_logic_vector(to_signed(500, DATA_WIDTH));
        ibeta_i      <= std_logic_vector(to_signed(-300, DATA_WIDTH));
        flux_alpha_i <= std_logic_vector(to_signed(1000, DATA_WIDTH));
        flux_beta_i  <= std_logic_vector(to_signed(-800, DATA_WIDTH));
        speed_mech_i <= std_logic_vector(to_signed(3600, DATA_WIDTH));

        -------------------------------------------------------
        -- TEST 1: Write VDC_BUS (addr 0x00) = 0xABCD
        -------------------------------------------------------
        report "TEST 1: Write VDC_BUS = 0xABCD" severity note;
        uart_write_reg(rx_i, 0, VDC_VAL);
        wait for BIT_PERIOD * 5;
        assert vdc_bus_o = VDC_VAL(DATA_WIDTH-1 downto 0)
            report "FAIL: VDC_BUS mismatch! Got: " &
                   integer'image(to_integer(signed(vdc_bus_o))) &
                   " Expected: " &
                   integer'image(to_integer(signed(VDC_VAL(DATA_WIDTH-1 downto 0))))
            severity error;
        report "TEST 1 PASSED: VDC_BUS written correctly" severity note;

        -------------------------------------------------------
        -- TEST 2: Write TORQUE_LOAD (addr 0x01) = 0x1234
        -------------------------------------------------------
        report "TEST 2: Write TORQUE_LOAD = 0x1234" severity note;
        uart_write_reg(rx_i, 1, TOR_VAL);
        wait for BIT_PERIOD * 5;
        assert torque_load_o = TOR_VAL(DATA_WIDTH-1 downto 0)
            report "FAIL: TORQUE_LOAD mismatch! Got: " &
                   integer'image(to_integer(signed(torque_load_o))) &
                   " Expected: " &
                   integer'image(to_integer(signed(TOR_VAL(DATA_WIDTH-1 downto 0))))
            severity error;
        report "TEST 2 PASSED: TORQUE_LOAD written correctly" severity note;

        -------------------------------------------------------
        -- TEST 3: Read back VDC_BUS (addr 0x00) via UART
        -------------------------------------------------------
        report "TEST 3: Read VDC_BUS" severity note;
        uart_read_reg(rx_i, tx_o, 0, hdr_v, addr_v, data_v, ok_v);
        if ok_v then
            assert hdr_v = x"AA"
                report "FAIL: Read header mismatch! Got: " &
                       integer'image(to_integer(unsigned(hdr_v))) &
                       " Expected: 170"
                severity error;
            assert addr_v = x"00"
                report "FAIL: Read addr mismatch! Got: " &
                       integer'image(to_integer(unsigned(addr_v)))
                severity error;
            assert data_v(DATA_WIDTH-1 downto 0) = VDC_VAL(DATA_WIDTH-1 downto 0)
                report "FAIL: Read data mismatch! Got: " &
                       integer'image(to_integer(signed(data_v(DATA_WIDTH-1 downto 0)))) &
                       " Expected: " &
                       integer'image(to_integer(signed(VDC_VAL(DATA_WIDTH-1 downto 0))))
                severity error;
            report "TEST 3 PASSED: VDC_BUS readback OK" severity note;
        else
            report "TEST 3 FAILED: Timeout receiving read response" severity error;
        end if;

        -------------------------------------------------------
        -- TEST 4: Read SPEED_MECH (addr 0x09) = 3600
        -------------------------------------------------------
        report "TEST 4: Read SPEED_MECH" severity note;
        uart_read_reg(rx_i, tx_o, 9, hdr_v, addr_v, data_v, ok_v);
        if ok_v then
            assert hdr_v = x"AA"
                report "FAIL: Read header mismatch!" severity error;
            assert addr_v = x"09"
                report "FAIL: Read addr mismatch! Got: " &
                       integer'image(to_integer(unsigned(addr_v)))
                severity error;
            assert data_v(DATA_WIDTH-1 downto 0) = std_logic_vector(to_signed(3600, DATA_WIDTH))
                report "FAIL: SPEED_MECH mismatch! Got: " &
                       integer'image(to_integer(signed(data_v(DATA_WIDTH-1 downto 0)))) &
                       " Expected: 3600"
                severity error;
            report "TEST 4 PASSED: SPEED_MECH readback OK" severity note;
        else
            report "TEST 4 FAILED: Timeout receiving read response" severity error;
        end if;

        -------------------------------------------------------
        -- TEST 5: Read All command
        -------------------------------------------------------
        report "TEST 5: Read All Registers" severity note;
        uart_send_byte(rx_i, x"41");
        -- Capture header (uart_recv_byte waits for start bit automatically)
        uart_recv_byte(tx_o, hdr_v, ok_v);
        if not ok_v then
            report "TEST 5 FAILED: Timeout on header" severity error;
        else
            assert hdr_v = x"55"
                report "FAIL: ReadAll header mismatch! Got: " &
                       integer'image(to_integer(unsigned(hdr_v)))
                severity error;
            -- Read 10 registers x 6 bytes each
            for reg_idx in 0 to 9 loop
                data_v := (others => '0');
                for byte_idx in BYTES_PER_WORD-1 downto 0 loop
                    uart_recv_byte(tx_o, byte_tmp, ok_v);
                    if not ok_v then
                        report "TEST 5 FAILED: Timeout on reg " &
                               integer'image(reg_idx)
                            severity error;
                        exit;
                    end if;
                    data_v(byte_idx*8+7 downto byte_idx*8) := byte_tmp;
                end loop;
                report "  Reg[" & integer'image(reg_idx) & "] = " &
                       integer'image(to_integer(signed(data_v(DATA_WIDTH-1 downto 0))))
                    severity note;
            end loop;
            report "TEST 5 PASSED: Read All completed" severity note;
        end if;

        -------------------------------------------------------
        -- Done
        -------------------------------------------------------
        report "======================================" severity note;
        report "ALL TESTS COMPLETED" severity note;
        report "======================================" severity note;
        wait for BIT_PERIOD * 2;
        sim_done <= true;
        wait;
    end process;

end architecture;
