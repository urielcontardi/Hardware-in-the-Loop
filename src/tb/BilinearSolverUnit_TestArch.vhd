-- =============================================================================
-- BilinearSolverUnit_TestArch.vhd
--
-- Two test-only architectures of BilinearSolverUnit that force a specific
-- BilienarSolverUnit_DSP implementation via direct entity instantiation.
-- These architectures are functionally identical to "rtl" — only the DSP
-- binding differs.
--
--   rtl_stub  →  BilienarSolverUnit_DSP(behavior)             (GHDL/NVC stub)
--   rtl_ip    →  BilienarSolverUnit_DSP(bilienarsolverunit_dsp_arch) (Xilinx IP)
--
-- Usage in testbench:
--   u_stub : entity work.BilinearSolverUnit(rtl_stub) ...
--   u_ip   : entity work.BilinearSolverUnit(rtl_ip)   ...
--
-- Compilation order: BilinearSolverUnit.vhd must be compiled first.
-- =============================================================================

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.BilinearSolverPkg.all;

-- =============================================================================
-- rtl_stub: behavioral DSP stub (same as GHDL/NVC cocotb simulation)
-- =============================================================================
Architecture rtl_stub of BilinearSolverUnit is

    constant TOTAL_OPERATIONS : integer := N_SS + N_IN;
    constant MULTIPLIER_DELAY : integer := 7;
    constant FIXED_POINT_ONE  : fixed_point_data_t :=
        std_logic_vector(to_signed(2**FP_FRACTION_BITS, FP_TOTAL_BITS));

    signal operand1_vec   : vector_fp_t(0 to TOTAL_OPERATIONS - 1);
    signal operand2_vec   : vector_fp_t(0 to TOTAL_OPERATIONS - 1);
    signal operand3_vec   : vector_fp_t(0 to TOTAL_OPERATIONS - 1);
    signal operand1       : fixed_point_data_t;
    signal operand2       : fixed_point_data_t;
    signal operand3       : fixed_point_data_t;

    signal pipeline1      : std_logic_vector(MULTIPLIER_DELAY - 1 downto 0) := (others => '0');
    signal pipeline2      : std_logic_vector(MULTIPLIER_DELAY - 1 downto 0) := (others => '0');
    signal index1         : integer range 0 to TOTAL_OPERATIONS;
    signal index2         : integer range 0 to TOTAL_OPERATIONS;
    signal pipeline3_tgr  : std_logic := '0';
    signal busy           : std_logic := '0';

    signal product1_raw     : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0);
    signal product1_rounded : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0);
    signal product1         : fixed_point_data_t;
    signal product2_raw     : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0);

    constant ROUND_HALF_P1 : signed((2*FP_TOTAL_BITS)-1 downto 0) :=
        to_signed(2**(FP_FRACTION_BITS-1), 2*FP_TOTAL_BITS);
    constant ROUND_HALF_P2 : signed((2*FP_TOTAL_BITS)-1 downto 0) :=
        to_signed(2**(FP_FRACTION_BITS-1), 2*FP_TOTAL_BITS);

    signal acmtr         : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0) := (others => '0');
    signal acmtr_rounded : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0);

Begin

    acmtr_rounded <= std_logic_vector(signed(acmtr) + ROUND_HALF_P2);
    stateResult_o <= acmtr_rounded(FP_TOTAL_BITS + FP_FRACTION_BITS - 1 downto FP_FRACTION_BITS);
    busy_o        <= busy;

    Operand1Assign : process(Xvec_i, Bvec_i)
    begin
        for i in 0 to N_SS - 1 loop
            operand1_vec(i) <= Xvec_i(i);
        end loop;
        for j in 0 to N_IN - 1 loop
            operand1_vec(N_SS + j) <= Bvec_i(j);
        end loop;
    end process;

    YVec : process(Yvec_i, Xvec_i, Uvec_i)
        variable index : integer range 0 to N_SS - 1;
    begin
        for aa in 0 to N_SS - 1 loop
            if is_x(Yvec_i(aa)) or Yvec_i(aa)(FP_TOTAL_BITS - 1) = '1' then
                operand2_vec(aa) <= FIXED_POINT_ONE;
            else
                index := to_integer(signed(Yvec_i(aa)));
                operand2_vec(aa) <= Xvec_i(index);
            end if;
        end loop;
        for j in 0 to N_IN - 1 loop
            operand2_vec(N_SS + j) <= Uvec_i(j);
        end loop;
    end process;

    Operand3Assign : process(Avec_i)
    begin
        for i in 0 to N_SS - 1 loop
            operand3_vec(i) <= Avec_i(i);
        end loop;
        for i in N_SS to TOTAL_OPERATIONS - 1 loop
            operand3_vec(i) <= FIXED_POINT_ONE;
        end loop;
    end process;

    -- ── Forced binding: behavioral stub (self-contained entity) ─────────────
    Multiplier1 : entity work.BilienarSolverUnit_DSP_Sim
        port map (CLK => sysclk, A => operand1, B => operand2, P => product1_raw);

    operand1         <= operand1_vec(index1);
    operand2         <= operand2_vec(index1);
    product1_rounded <= std_logic_vector(signed(product1_raw) + ROUND_HALF_P1);
    product1         <= product1_rounded(FP_TOTAL_BITS + FP_FRACTION_BITS - 1 downto FP_FRACTION_BITS);

    Multiplier2 : entity work.BilienarSolverUnit_DSP_Sim
        port map (CLK => sysclk, A => product1, B => operand3, P => product2_raw);

    operand3 <= operand3_vec(index2);

    process(sysclk)
        variable pipeline1_tgr : std_logic := '0';
        variable pipeline2_tgr : std_logic := '0';
    begin
        if rising_edge(sysclk) then
            if start_i = '1' and busy = '0' then
                pipeline1_tgr := '1';
            elsif index1 = TOTAL_OPERATIONS - 1 then
                pipeline1_tgr := '0';
            end if;

            pipeline1 <= pipeline1(pipeline1'left - 1 downto 0) & pipeline1_tgr;
            if pipeline1(pipeline1'right) = '1' and index1 < TOTAL_OPERATIONS - 1 then
                index1 <= index1 + 1;
            else
                index1 <= 0;
            end if;

            pipeline2_tgr := pipeline1(pipeline1'left);
            pipeline2 <= pipeline2(pipeline2'left - 1 downto 0) & pipeline2_tgr;
            if pipeline2(pipeline2'right) = '1' and index2 < TOTAL_OPERATIONS - 1 then
                index2 <= index2 + 1;
            else
                index2 <= 0;
            end if;

            pipeline3_tgr <= pipeline2(pipeline2'left);
            if start_i = '1' and busy = '0' then
                acmtr <= (others => '0');
            elsif pipeline3_tgr = '1' then
                acmtr <= std_logic_vector(signed(acmtr) + signed(product2_raw));
            end if;

            if start_i = '1' then
                busy <= '1';
            elsif pipeline1 = (pipeline1'range => '0') and
                  pipeline2 = (pipeline2'range => '0') and
                  pipeline3_tgr = '0' then
                busy <= '0';
            end if;
        end if;
    end process;

End architecture;


-- =============================================================================
-- rtl_ip: Xilinx mult_gen IP (DSP48E1 behavioral model, xsim only)
-- =============================================================================
Architecture rtl_ip of BilinearSolverUnit is

    constant TOTAL_OPERATIONS : integer := N_SS + N_IN;
    constant MULTIPLIER_DELAY : integer := 7;
    constant FIXED_POINT_ONE  : fixed_point_data_t :=
        std_logic_vector(to_signed(2**FP_FRACTION_BITS, FP_TOTAL_BITS));

    signal operand1_vec   : vector_fp_t(0 to TOTAL_OPERATIONS - 1);
    signal operand2_vec   : vector_fp_t(0 to TOTAL_OPERATIONS - 1);
    signal operand3_vec   : vector_fp_t(0 to TOTAL_OPERATIONS - 1);
    signal operand1       : fixed_point_data_t;
    signal operand2       : fixed_point_data_t;
    signal operand3       : fixed_point_data_t;

    signal pipeline1      : std_logic_vector(MULTIPLIER_DELAY - 1 downto 0) := (others => '0');
    signal pipeline2      : std_logic_vector(MULTIPLIER_DELAY - 1 downto 0) := (others => '0');
    signal index1         : integer range 0 to TOTAL_OPERATIONS;
    signal index2         : integer range 0 to TOTAL_OPERATIONS;
    signal pipeline3_tgr  : std_logic := '0';
    signal busy           : std_logic := '0';

    signal product1_raw     : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0);
    signal product1_rounded : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0);
    signal product1         : fixed_point_data_t;
    signal product2_raw     : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0);

    constant ROUND_HALF_P1 : signed((2*FP_TOTAL_BITS)-1 downto 0) :=
        to_signed(2**(FP_FRACTION_BITS-1), 2*FP_TOTAL_BITS);
    constant ROUND_HALF_P2 : signed((2*FP_TOTAL_BITS)-1 downto 0) :=
        to_signed(2**(FP_FRACTION_BITS-1), 2*FP_TOTAL_BITS);

    signal acmtr         : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0) := (others => '0');
    signal acmtr_rounded : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0);

Begin

    acmtr_rounded <= std_logic_vector(signed(acmtr) + ROUND_HALF_P2);
    stateResult_o <= acmtr_rounded(FP_TOTAL_BITS + FP_FRACTION_BITS - 1 downto FP_FRACTION_BITS);
    busy_o        <= busy;

    Operand1Assign : process(Xvec_i, Bvec_i)
    begin
        for i in 0 to N_SS - 1 loop
            operand1_vec(i) <= Xvec_i(i);
        end loop;
        for j in 0 to N_IN - 1 loop
            operand1_vec(N_SS + j) <= Bvec_i(j);
        end loop;
    end process;

    YVec : process(Yvec_i, Xvec_i, Uvec_i)
        variable index : integer range 0 to N_SS - 1;
    begin
        for aa in 0 to N_SS - 1 loop
            if is_x(Yvec_i(aa)) or Yvec_i(aa)(FP_TOTAL_BITS - 1) = '1' then
                operand2_vec(aa) <= FIXED_POINT_ONE;
            else
                index := to_integer(signed(Yvec_i(aa)));
                operand2_vec(aa) <= Xvec_i(index);
            end if;
        end loop;
        for j in 0 to N_IN - 1 loop
            operand2_vec(N_SS + j) <= Uvec_i(j);
        end loop;
    end process;

    Operand3Assign : process(Avec_i)
    begin
        for i in 0 to N_SS - 1 loop
            operand3_vec(i) <= Avec_i(i);
        end loop;
        for i in N_SS to TOTAL_OPERATIONS - 1 loop
            operand3_vec(i) <= FIXED_POINT_ONE;
        end loop;
    end process;

    -- ── Forced binding: Xilinx mult_gen IP sim model ─────────────────────────
    Multiplier1 : entity work.BilienarSolverUnit_DSP(bilienarsolverunit_dsp_arch)
        port map (CLK => sysclk, A => operand1, B => operand2, P => product1_raw);

    operand1         <= operand1_vec(index1);
    operand2         <= operand2_vec(index1);
    product1_rounded <= std_logic_vector(signed(product1_raw) + ROUND_HALF_P1);
    product1         <= product1_rounded(FP_TOTAL_BITS + FP_FRACTION_BITS - 1 downto FP_FRACTION_BITS);

    Multiplier2 : entity work.BilienarSolverUnit_DSP(bilienarsolverunit_dsp_arch)
        port map (CLK => sysclk, A => product1, B => operand3, P => product2_raw);

    operand3 <= operand3_vec(index2);

    process(sysclk)
        variable pipeline1_tgr : std_logic := '0';
        variable pipeline2_tgr : std_logic := '0';
    begin
        if rising_edge(sysclk) then
            if start_i = '1' and busy = '0' then
                pipeline1_tgr := '1';
            elsif index1 = TOTAL_OPERATIONS - 1 then
                pipeline1_tgr := '0';
            end if;

            pipeline1 <= pipeline1(pipeline1'left - 1 downto 0) & pipeline1_tgr;
            if pipeline1(pipeline1'right) = '1' and index1 < TOTAL_OPERATIONS - 1 then
                index1 <= index1 + 1;
            else
                index1 <= 0;
            end if;

            pipeline2_tgr := pipeline1(pipeline1'left);
            pipeline2 <= pipeline2(pipeline2'left - 1 downto 0) & pipeline2_tgr;
            if pipeline2(pipeline2'right) = '1' and index2 < TOTAL_OPERATIONS - 1 then
                index2 <= index2 + 1;
            else
                index2 <= 0;
            end if;

            pipeline3_tgr <= pipeline2(pipeline2'left);
            if start_i = '1' and busy = '0' then
                acmtr <= (others => '0');
            elsif pipeline3_tgr = '1' then
                acmtr <= std_logic_vector(signed(acmtr) + signed(product2_raw));
            end if;

            if start_i = '1' then
                busy <= '1';
            elsif pipeline1 = (pipeline1'range => '0') and
                  pipeline2 = (pipeline2'range => '0') and
                  pipeline3_tgr = '0' then
                busy <= '0';
            end if;
        end if;
    end process;

End architecture;
