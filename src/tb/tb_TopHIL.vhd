-- Top_HIL compile/smoke test. No external files or machine-specific paths.
library ieee;
use ieee.std_logic_1164.all;
use std.env.finish;

entity tb_TopHIL is
end entity;

architecture sim of tb_TopHIL is
    constant CLK_PERIOD : time := 10 ns;
    signal clk          : std_logic := '0';
    signal reset_n      : std_logic := '0';
    signal pwm_enb      : std_logic := '0';
    signal pwm_clear    : std_logic := '0';
    signal va_ref       : std_logic_vector(31 downto 0) := (others => '0');
    signal vb_ref       : std_logic_vector(31 downto 0) := (others => '0');
    signal vc_ref       : std_logic_vector(31 downto 0) := (others => '0');
    signal carrier_tick : std_logic;
    signal sample_tick  : std_logic;
    signal pwm_on       : std_logic;
    signal pwm_fault    : std_logic;
    signal pwm_a        : std_logic_vector(3 downto 0);
    signal pwm_b        : std_logic_vector(3 downto 0);
    signal pwm_c        : std_logic_vector(3 downto 0);
    signal uart_tx      : std_logic;
begin
    clk <= not clk after CLK_PERIOD / 2;

    uut : entity work.Top_HIL
        generic map (
            CLK_FREQUENCY   => 100_000_000,
            PWM_FREQUENCY   => 1_000,
            MIN_PULSE_WIDTH => 1,
            DEAD_TIME       => 1
        )
        port map (
            clk_i          => clk,
            reset_n        => reset_n,
            pwm_enb_i      => pwm_enb,
            pwm_clear_i    => pwm_clear,
            va_ref_i       => va_ref,
            vb_ref_i       => vb_ref,
            vc_ref_i       => vc_ref,
            carrier_tick_o => carrier_tick,
            sample_tick_o  => sample_tick,
            pwm_on_o       => pwm_on,
            pwm_fault_o    => pwm_fault,
            pwm_a_o        => pwm_a,
            pwm_b_o        => pwm_b,
            pwm_c_o        => pwm_c,
            uart_rx_i      => '1',
            uart_tx_o      => uart_tx
        );

    stimulus : process
    begin
        wait for 10 * CLK_PERIOD;
        reset_n <= '1';
        pwm_enb <= '1';
        wait for 2 ms;
        assert pwm_fault = '0' report "unexpected PWM fault" severity failure;
        report "tb_TopHIL PASS" severity note;
        finish;
    end process;
end architecture;
