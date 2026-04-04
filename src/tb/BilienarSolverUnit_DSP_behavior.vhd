-- Simulation-only architecture body for BilienarSolverUnit_DSP.
--
-- Used exclusively in the sim_compare fileset to compile the 'behavior'
-- architecture against the Xilinx IP entity declaration (no generics),
-- allowing both architectures to coexist in the same library.
--
-- LATENCY is hardcoded to 7 to match the IP configuration.
-- Do NOT use this file in synthesis or standalone simulation.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

architecture behavior of BilienarSolverUnit_DSP is
    constant LATENCY : natural := 7;
    type pipe_t is array (0 to LATENCY-1) of std_logic_vector(83 downto 0);
    signal pipe_reg : pipe_t := (others => (others => '0'));
begin

    process(CLK)
        variable product_v : signed(83 downto 0);
    begin
        if rising_edge(CLK) then
            product_v := signed(A) * signed(B);
            pipe_reg(0) <= std_logic_vector(product_v);
            for i in 1 to LATENCY-1 loop
                pipe_reg(i) <= pipe_reg(i-1);
            end loop;
        end if;
    end process;

    P <= pipe_reg(LATENCY-1);

end architecture;
