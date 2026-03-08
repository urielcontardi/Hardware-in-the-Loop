--! \file       SerialManager.vhd
--!
--! \brief      Serial Manager Module using UART
--!             Provides a register-based interface over UART for configuring
--!             and monitoring the HIL system.
--!
--!             PROTOCOL:
--!             All register values are BYTES_PER_WORD bytes wide (big-endian, sign-extended).
--!             BYTES_PER_WORD = ceil(DATA_WIDTH / 8)  (e.g. 6 bytes for 42-bit data).
--!
--!             RX Commands (Host -> FPGA):
--!               Write:    'W' (0x57) | ADDR (1B) | DATA (BYTES_PER_WORD bytes, MSB first)
--!               Read:     'R' (0x52) | ADDR (1B)
--!               Read All: 'A' (0x41)
--!
--!             TX Responses (FPGA -> Host):
--!               Read response:     0xAA | ADDR (1B) | DATA (BYTES_PER_WORD bytes, MSB first)
--!               Read All response: 0x55 | REG0_DATA | REG1_DATA | ... | REG9_DATA
--!                                  (10 x BYTES_PER_WORD bytes, addresses 0x00..0x09 in order)
--!
--!             REGISTER MAP:
--!               Addr 0x00  VDC_BUS       (R/W)  DC bus voltage
--!               Addr 0x01  TORQUE_LOAD   (R/W)  Motor load torque
--!               Addr 0x02  VA_MOTOR      (R)    Motor voltage phase A
--!               Addr 0x03  VB_MOTOR      (R)    Motor voltage phase B
--!               Addr 0x04  VC_MOTOR      (R)    Motor voltage phase C
--!               Addr 0x05  I_ALPHA       (R)    Stator current alpha
--!               Addr 0x06  I_BETA        (R)    Stator current beta
--!               Addr 0x07  FLUX_ALPHA    (R)    Rotor flux alpha
--!               Addr 0x08  FLUX_BETA     (R)    Rotor flux beta
--!               Addr 0x09  SPEED_MECH    (R)    Mechanical speed
--!
--! \author     Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       16-02-2026
--!
--! \version    1.1
--!
--! \copyright  Copyright (c) 2026 - All Rights reserved.
--!
--! \note       Target devices : Xilinx 7-series, UltraScale
--! \note       Tool versions  : Vivado 2020.2+
--! \note       Dependencies   : UartFull.vhd

--------------------------------------------------------------------------
-- Default libraries
--------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity SerialManager is
    Generic (
        CLK_FREQ        : natural := 200_000_000;   --! System clock frequency (Hz)
        BAUD_RATE       : natural := 115200;         --! UART baud rate (bps)
        DATA_WIDTH      : natural := 42              --! Register data width (bits)
    );
    Port (
        clk_i           : in  std_logic;             --! System clock
        reset_n_i       : in  std_logic;             --! Active-low reset

        --------------------------------------------------------------------------
        -- UART Physical Interface
        --------------------------------------------------------------------------
        rx_i            : in  std_logic;             --! UART RX line
        tx_o            : out std_logic;             --! UART TX line

        --------------------------------------------------------------------------
        -- Configuration Outputs (writable registers -> system)
        --------------------------------------------------------------------------
        vdc_bus_o       : out std_logic_vector(DATA_WIDTH-1 downto 0);   --! DC bus voltage
        torque_load_o   : out std_logic_vector(DATA_WIDTH-1 downto 0);   --! Motor load torque
        config_valid_o  : out std_logic;             --! Pulse when a config register is updated

        --------------------------------------------------------------------------
        -- Monitor Inputs (system -> readable registers)
        --------------------------------------------------------------------------
        va_motor_i      : in  std_logic_vector(DATA_WIDTH-1 downto 0);  --! Motor voltage A
        vb_motor_i      : in  std_logic_vector(DATA_WIDTH-1 downto 0);  --! Motor voltage B
        vc_motor_i      : in  std_logic_vector(DATA_WIDTH-1 downto 0);  --! Motor voltage C
        ialpha_i        : in  std_logic_vector(DATA_WIDTH-1 downto 0);  --! Stator current alpha
        ibeta_i         : in  std_logic_vector(DATA_WIDTH-1 downto 0);  --! Stator current beta
        flux_alpha_i    : in  std_logic_vector(DATA_WIDTH-1 downto 0);  --! Rotor flux alpha
        flux_beta_i     : in  std_logic_vector(DATA_WIDTH-1 downto 0);  --! Rotor flux beta
        speed_mech_i    : in  std_logic_vector(DATA_WIDTH-1 downto 0);  --! Mechanical speed
        data_valid_i    : in  std_logic              --! Data valid strobe from TIM solver
    );
End entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
Architecture rtl of SerialManager is

    --------------------------------------------------------------------------
    -- Constants
    --------------------------------------------------------------------------
    constant BYTES_PER_WORD : natural := (DATA_WIDTH + 7) / 8;  -- 6 for 42-bit
    constant WORD_WIDTH     : natural := BYTES_PER_WORD * 8;     -- 48 for 42-bit
    constant NUM_REGS       : natural := 10;

    -- Command bytes
    constant CMD_WRITE      : std_logic_vector(7 downto 0) := x"57";  -- 'W'
    constant CMD_READ       : std_logic_vector(7 downto 0) := x"52";  -- 'R'
    constant CMD_READ_ALL   : std_logic_vector(7 downto 0) := x"41";  -- 'A'

    -- Response headers
    constant RSP_SINGLE     : std_logic_vector(7 downto 0) := x"AA";
    constant RSP_ALL        : std_logic_vector(7 downto 0) := x"55";

    --------------------------------------------------------------------------
    -- UART Signals
    --------------------------------------------------------------------------
    signal rx_data          : std_logic_vector(7 downto 0);
    signal rx_rd_en         : std_logic;
    signal rx_empty         : std_logic;
    signal tx_data          : std_logic_vector(7 downto 0);
    signal tx_wr_en         : std_logic;
    signal tx_full          : std_logic;

    --------------------------------------------------------------------------
    -- Configuration Registers (writable via UART)
    --------------------------------------------------------------------------
    signal vdc_bus_reg      : std_logic_vector(DATA_WIDTH-1 downto 0) := (others => '0');
    signal torque_load_reg  : std_logic_vector(DATA_WIDTH-1 downto 0) := (others => '0');
    signal config_valid_int : std_logic := '0';

    --------------------------------------------------------------------------
    -- Main FSM (single process handles both RX parsing and TX response)
    -- This avoids the multi-driver issue of separate RX/TX processes.
    --------------------------------------------------------------------------
    type state_t is (
        -- RX states
        ST_IDLE,
        ST_RX_WAIT,
        ST_RX_GET_ADDR,
        ST_RX_GET_DATA,
        ST_RX_EXECUTE,
        -- TX states
        ST_TX_HEADER,
        ST_TX_ADDR,
        ST_TX_LOAD,
        ST_TX_SEND_BYTE
    );
    signal state            : state_t := ST_IDLE;
    signal next_rx_state    : state_t;
    signal rx_cmd           : std_logic_vector(7 downto 0);
    signal rx_reg_addr      : natural range 0 to 15;
    signal rx_word_buf      : std_logic_vector(WORD_WIDTH-1 downto 0);
    signal rx_byte_cnt      : natural range 0 to BYTES_PER_WORD;
    signal rx_wait_cnt      : natural range 0 to 1 := 0;

    --------------------------------------------------------------------------
    -- TX control signals
    --------------------------------------------------------------------------
    signal tx_shift         : std_logic_vector(WORD_WIDTH-1 downto 0);
    signal tx_byte_cnt      : natural range 0 to BYTES_PER_WORD;
    signal tx_reg_idx       : natural range 0 to 15;
    signal tx_reg_last      : natural range 0 to 15;
    signal tx_is_single     : std_logic;

    --------------------------------------------------------------------------
    -- Register Mux (for TX readback)
    --------------------------------------------------------------------------
    signal tx_mux_data      : std_logic_vector(WORD_WIDTH-1 downto 0);

Begin

    --------------------------------------------------------------------------
    -- UART Instance
    --------------------------------------------------------------------------
    UART_Inst : entity work.UartFull
    generic map (
        G_CLK_FREQ      => CLK_FREQ,
        G_BAUD_RATE     => BAUD_RATE,
        G_DATA_WIDTH    => 8,
        G_TX_FIFO_DEPTH => 7,
        G_RX_FIFO_DEPTH => 4
    )
    port map (
        clk_i           => clk_i,
        rst_n_i         => reset_n_i,
        -- TX
        tx_data_i       => tx_data,
        tx_wr_en_i      => tx_wr_en,
        tx_enable_i     => '1',
        tx_full_o       => tx_full,
        tx_empty_o      => open,
        tx_count_o      => open,
        -- RX
        rx_data_o       => rx_data,
        rx_rd_en_i      => rx_rd_en,
        rx_empty_o      => rx_empty,
        rx_full_o       => open,
        rx_count_o      => open,
        -- Status
        rx_error_o      => open,
        rx_timeout_o    => open,
        tx_busy_o       => open,
        rx_busy_o       => open,
        -- Physical
        tx_o            => tx_o,
        rx_i            => rx_i
    );

    --------------------------------------------------------------------------
    -- Register Mux: Select register value by address (combinational)
    --------------------------------------------------------------------------
    RegMux_Proc : process(tx_reg_idx, vdc_bus_reg, torque_load_reg,
                          va_motor_i, vb_motor_i, vc_motor_i,
                          ialpha_i, ibeta_i,
                          flux_alpha_i, flux_beta_i, speed_mech_i)
    begin
        case tx_reg_idx is
            when 0      => tx_mux_data <= std_logic_vector(resize(signed(vdc_bus_reg),     WORD_WIDTH));
            when 1      => tx_mux_data <= std_logic_vector(resize(signed(torque_load_reg), WORD_WIDTH));
            when 2      => tx_mux_data <= std_logic_vector(resize(signed(va_motor_i),      WORD_WIDTH));
            when 3      => tx_mux_data <= std_logic_vector(resize(signed(vb_motor_i),      WORD_WIDTH));
            when 4      => tx_mux_data <= std_logic_vector(resize(signed(vc_motor_i),      WORD_WIDTH));
            when 5      => tx_mux_data <= std_logic_vector(resize(signed(ialpha_i),        WORD_WIDTH));
            when 6      => tx_mux_data <= std_logic_vector(resize(signed(ibeta_i),         WORD_WIDTH));
            when 7      => tx_mux_data <= std_logic_vector(resize(signed(flux_alpha_i),    WORD_WIDTH));
            when 8      => tx_mux_data <= std_logic_vector(resize(signed(flux_beta_i),     WORD_WIDTH));
            when 9      => tx_mux_data <= std_logic_vector(resize(signed(speed_mech_i),    WORD_WIDTH));
            when others => tx_mux_data <= (others => '0');
        end case;
    end process;

    --------------------------------------------------------------------------
    -- Main FSM Process
    --------------------------------------------------------------------------
    Main_FSM_Proc : process(clk_i, reset_n_i)
    begin
        if reset_n_i = '0' then
            state           <= ST_IDLE;
            rx_rd_en        <= '0';
            tx_wr_en        <= '0';
            config_valid_int <= '0';
            rx_wait_cnt     <= 0;
            vdc_bus_reg     <= (others => '0');
            torque_load_reg <= (others => '0');

        elsif rising_edge(clk_i) then
            rx_rd_en         <= '0';
            tx_wr_en         <= '0';
            config_valid_int <= '0';

            case state is

                --------------------------------------------------------
                -- IDLE: Wait for command byte in RX FIFO
                --------------------------------------------------------
                when ST_IDLE =>
                    if rx_empty = '0' then
                        rx_cmd   <= rx_data;
                        rx_rd_en <= '1';
                        if rx_data = CMD_READ_ALL then
                            -- No address/data bytes needed, go straight to TX
                            tx_is_single <= '0';
                            tx_reg_idx   <= 0;
                            tx_reg_last  <= NUM_REGS - 1;
                            state        <= ST_TX_HEADER;
                        else
                            -- Need at least an address byte next
                            next_rx_state <= ST_RX_GET_ADDR;
                            state         <= ST_RX_WAIT;
                        end if;
                    end if;

                --------------------------------------------------------
                -- RX_WAIT: 2-cycle delay for registered FIFO output
                --------------------------------------------------------
                when ST_RX_WAIT =>
                    if rx_wait_cnt = 0 then
                        rx_wait_cnt <= 1;
                    else
                        rx_wait_cnt <= 0;
                        state       <= next_rx_state;
                    end if;

                --------------------------------------------------------
                -- GET_ADDR: Read register address byte
                --------------------------------------------------------
                when ST_RX_GET_ADDR =>
                    if rx_empty = '0' then
                        rx_reg_addr <= to_integer(unsigned(rx_data(3 downto 0)));
                        rx_rd_en    <= '1';

                        if rx_cmd = CMD_WRITE then
                            rx_byte_cnt   <= 0;
                            rx_word_buf   <= (others => '0');
                            next_rx_state <= ST_RX_GET_DATA;
                            state         <= ST_RX_WAIT;
                        elsif rx_cmd = CMD_READ then
                            -- Single-register read: go directly to TX
                            tx_is_single <= '1';
                            tx_reg_idx   <= to_integer(unsigned(rx_data(3 downto 0)));
                            tx_reg_last  <= to_integer(unsigned(rx_data(3 downto 0)));
                            state        <= ST_TX_HEADER;
                        else
                            state <= ST_IDLE;
                        end if;
                    end if;

                --------------------------------------------------------
                -- GET_DATA: Receive BYTES_PER_WORD data bytes (MSB first)
                --------------------------------------------------------
                when ST_RX_GET_DATA =>
                    if rx_empty = '0' then
                        rx_word_buf(WORD_WIDTH-1 downto 8) <= rx_word_buf(WORD_WIDTH-9 downto 0);
                        rx_word_buf(7 downto 0)            <= rx_data;
                        rx_rd_en    <= '1';
                        rx_byte_cnt <= rx_byte_cnt + 1;

                        if rx_byte_cnt = BYTES_PER_WORD - 1 then
                            state <= ST_RX_EXECUTE;
                        else
                            next_rx_state <= ST_RX_GET_DATA;
                            state         <= ST_RX_WAIT;
                        end if;
                    end if;

                --------------------------------------------------------
                -- EXECUTE: Write received value to config register
                --------------------------------------------------------
                when ST_RX_EXECUTE =>
                    case rx_reg_addr is
                        when 0 =>
                            vdc_bus_reg      <= rx_word_buf(DATA_WIDTH-1 downto 0);
                            config_valid_int <= '1';
                        when 1 =>
                            torque_load_reg  <= rx_word_buf(DATA_WIDTH-1 downto 0);
                            config_valid_int <= '1';
                        when others =>
                            null;
                    end case;
                    state <= ST_IDLE;

                --------------------------------------------------------
                -- TX_HEADER: Send response header byte
                --------------------------------------------------------
                when ST_TX_HEADER =>
                    if tx_full = '0' then
                        if tx_is_single = '1' then
                            tx_data <= RSP_SINGLE;
                        else
                            tx_data <= RSP_ALL;
                        end if;
                        tx_wr_en <= '1';
                        if tx_is_single = '1' then
                            state <= ST_TX_ADDR;
                        else
                            state <= ST_TX_LOAD;
                        end if;
                    end if;

                --------------------------------------------------------
                -- TX_ADDR: Send register address byte (single read only)
                --------------------------------------------------------
                when ST_TX_ADDR =>
                    if tx_full = '0' then
                        tx_data  <= std_logic_vector(to_unsigned(tx_reg_idx, 8));
                        tx_wr_en <= '1';
                        state    <= ST_TX_LOAD;
                    end if;

                --------------------------------------------------------
                -- TX_LOAD: Load shift register from register mux
                --------------------------------------------------------
                when ST_TX_LOAD =>
                    tx_shift    <= tx_mux_data;
                    tx_byte_cnt <= BYTES_PER_WORD;
                    state       <= ST_TX_SEND_BYTE;

                --------------------------------------------------------
                -- TX_SEND_BYTE: Send one byte at a time from shift reg
                --------------------------------------------------------
                when ST_TX_SEND_BYTE =>
                    if tx_full = '0' and tx_byte_cnt > 0 then
                        tx_data  <= tx_shift(WORD_WIDTH-1 downto WORD_WIDTH-8);
                        tx_wr_en <= '1';
                        tx_shift <= tx_shift(WORD_WIDTH-9 downto 0) & x"00";
                        tx_byte_cnt <= tx_byte_cnt - 1;

                        if tx_byte_cnt = 1 then
                            if tx_reg_idx < tx_reg_last then
                                tx_reg_idx <= tx_reg_idx + 1;
                                state      <= ST_TX_LOAD;
                            else
                                state <= ST_IDLE;
                            end if;
                        end if;
                    end if;

            end case;
        end if;
    end process;

    --------------------------------------------------------------------------
    -- Output Assignments
    --------------------------------------------------------------------------
    vdc_bus_o      <= vdc_bus_reg;
    torque_load_o  <= torque_load_reg;
    config_valid_o <= config_valid_int;

End architecture;
