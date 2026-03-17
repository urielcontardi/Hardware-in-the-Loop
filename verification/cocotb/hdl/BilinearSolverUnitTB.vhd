-- Testbench wrapper for BilinearSolverUnit.
--
-- GHDL VPI cannot expose unconstrained array ports (vector_fp_t) as
-- hierarchical signals accessible by cocotb. This wrapper re-exposes the
-- solver with individual std_logic_vector scalars for each element, which
-- GHDL VPI does expose.
--
-- Parameters are fixed: N_SS=5, N_IN=3, FP_TOTAL_BITS=42
-- All port names are lowercase to match GHDL VPI convention.
--
-- Naming: avec_0..avec_4 (A row vector), xvec_0..xvec_4 (X state),
--         yvec_0..yvec_4 (Y bilinear index, raw integer),
--         bvec_0..bvec_2 (B input row), uvec_0..uvec_2 (U input vector)
--------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.BilinearSolverPkg.all;

entity BilinearSolverUnitTB is
    port (
        sysclk  : in  std_logic;
        start_i : in  std_logic;

        -- A vector row (N_SS=5 elements)
        avec_0 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        avec_1 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        avec_2 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        avec_3 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        avec_4 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);

        -- X state vector (N_SS=5 elements)
        xvec_0 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        xvec_1 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        xvec_2 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        xvec_3 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        xvec_4 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);

        -- Y bilinear index vector (N_SS=5 elements, raw signed integer)
        yvec_0 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        yvec_1 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        yvec_2 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        yvec_3 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        yvec_4 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);

        -- B input row (N_IN=3 elements)
        bvec_0 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        bvec_1 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        bvec_2 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);

        -- U input vector (N_IN=3 elements)
        uvec_0 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        uvec_1 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        uvec_2 : in std_logic_vector(FP_TOTAL_BITS-1 downto 0);

        -- Outputs
        stateresult_o : out std_logic_vector(FP_TOTAL_BITS-1 downto 0);
        busy_o        : out std_logic
    );
end entity;

architecture tb of BilinearSolverUnitTB is

    signal avec_s : vector_fp_t(0 to 4);
    signal xvec_s : vector_fp_t(0 to 4);
    signal yvec_s : vector_fp_t(0 to 4);
    signal bvec_s : vector_fp_t(0 to 2);
    signal uvec_s : vector_fp_t(0 to 2);

begin

    -- Unpack scalar ports into array signals
    avec_s(0) <= avec_0;  avec_s(1) <= avec_1;  avec_s(2) <= avec_2;
    avec_s(3) <= avec_3;  avec_s(4) <= avec_4;

    xvec_s(0) <= xvec_0;  xvec_s(1) <= xvec_1;  xvec_s(2) <= xvec_2;
    xvec_s(3) <= xvec_3;  xvec_s(4) <= xvec_4;

    yvec_s(0) <= yvec_0;  yvec_s(1) <= yvec_1;  yvec_s(2) <= yvec_2;
    yvec_s(3) <= yvec_3;  yvec_s(4) <= yvec_4;

    bvec_s(0) <= bvec_0;  bvec_s(1) <= bvec_1;  bvec_s(2) <= bvec_2;

    uvec_s(0) <= uvec_0;  uvec_s(1) <= uvec_1;  uvec_s(2) <= uvec_2;

    DUT : entity work.BilinearSolverUnit
        generic map (N_SS => 5, N_IN => 3)
        port map (
            sysclk        => sysclk,
            start_i       => start_i,
            Avec_i        => avec_s,
            Xvec_i        => xvec_s,
            Yvec_i        => yvec_s,
            Bvec_i        => bvec_s,
            Uvec_i        => uvec_s,
            stateResult_o => stateresult_o,
            busy_o        => busy_o
        );

end architecture;
