-- Behavioral simulation stub for the ClarkeMultiplier_DSP Xilinx mult_gen IP.
-- Synthesis uses the Vivado IP created in syn/hil/create_ebaz4205_project.tcl.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ClarkeMultiplier_DSP is
    generic (
        A_WIDTH : natural := 43;
        B_WIDTH : natural := 29;
        P_WIDTH : natural := 72;
        LATENCY : natural := 7
    );
    port (
        CLK : in  std_logic;
        A   : in  std_logic_vector(A_WIDTH - 1 downto 0);
        B   : in  std_logic_vector(B_WIDTH - 1 downto 0);
        P   : out std_logic_vector(P_WIDTH - 1 downto 0)
    );
end entity;

architecture behavior of ClarkeMultiplier_DSP is
    type pipe_t is array (0 to LATENCY - 1) of std_logic_vector(P_WIDTH - 1 downto 0);
    signal pipe_reg : pipe_t := (others => (others => '0'));
begin
    process(CLK)
        variable product_v : signed(P_WIDTH - 1 downto 0);
    begin
        if rising_edge(CLK) then
            product_v   := resize(signed(A) * signed(B), P_WIDTH);
            pipe_reg(0) <= std_logic_vector(product_v);
            for i in 1 to LATENCY - 1 loop
                pipe_reg(i) <= pipe_reg(i - 1);
            end loop;
        end if;
    end process;

    P <= pipe_reg(LATENCY - 1);
end architecture;
