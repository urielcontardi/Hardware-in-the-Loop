-- =============================================================================
-- BilienarSolverUnit_DSP_Sim.vhd
--
-- Simulation-only entity for the DSP48E1 behavioral stub.
-- Used in sim_compare and sim_bsu_compare (Vivado xsim) instead of the
-- architecture-only BilienarSolverUnit_DSP_behavior.vhd, which Vivado
-- auto-excludes from compile order when the primary entity comes from an IP.
--
-- Entity name is intentionally different from BilienarSolverUnit_DSP so
-- this file is a self-contained primary+secondary unit pair — Vivado always
-- includes such files in the compile order.
--
-- Port sizes match the Xilinx mult_gen IP (42-bit signed, 7-stage pipeline).
-- =============================================================================

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.BilinearSolverPkg.all;

entity BilienarSolverUnit_DSP_Sim is
    port (
        CLK : in  std_logic;
        A   : in  std_logic_vector(FP_TOTAL_BITS - 1 downto 0);
        B   : in  std_logic_vector(FP_TOTAL_BITS - 1 downto 0);
        P   : out std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0)
    );
end entity;

architecture behavior of BilienarSolverUnit_DSP_Sim is
    constant LATENCY : natural := 7;
    type pipe_t is array (0 to LATENCY-1) of std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0);
    signal pipe_reg : pipe_t := (others => (others => '0'));
begin
    process(CLK)
        variable product_v : signed((2*FP_TOTAL_BITS)-1 downto 0);
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
