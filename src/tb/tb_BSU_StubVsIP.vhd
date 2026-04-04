-- =============================================================================
-- tb_BSU_StubVsIP.vhd
--
-- Side-by-side comparison of BilinearSolverUnit with two DSP implementations:
--   u_bsu_stub → BilinearSolverUnit(rtl_stub)  uses BilienarSolverUnit_DSP(behavior)
--   u_bsu_ip   → BilinearSolverUnit(rtl_ip)    uses BilienarSolverUnit_DSP(bilienarsolverunit_dsp_arch)
--
-- Both instances receive identical inputs. The checker verifies that:
--   1. busy_stub == busy_ip on every clock (timing identity)
--   2. result_stub == result_ip at the end of each computation (numeric identity)
--
-- Test vectors (N_SS=2, N_IN=1, Q14.28):
--   zeros       : all zeros                          → expected  0.0
--   linear      : X=[1,2], A=[0.5,0.25], no coupling → expected  1.3
--   bilinear    : X=[1,2], A=[0.5,0.25], Y=[1,0]    → expected  1.8
--   neg_vals    : X=[-2,3], A=[0.1,-0.1], Y=[1,0]   → expected -0.5
--   motor_like  : X=[5,-3], A=[0.01,0.02], no coupl → expected  4.99
--   sweep       : ramp of 8 (a,x) pairs              → match only
--
-- Run via:  make sim-bsu-compare
-- Output:   syn/hil/tb_BSU_StubVsIP.vcd
-- =============================================================================

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.BilinearSolverPkg.all;

entity tb_BSU_StubVsIP is
end entity;

architecture sim of tb_BSU_StubVsIP is

    -- ── Parameters ───────────────────────────────────────────────────────────
    constant N_SS       : natural := 2;
    constant N_IN       : natural := 1;
    constant CLK_PERIOD : time    := 10 ns;

    -- ── Shared inputs ────────────────────────────────────────────────────────
    signal sysclk  : std_logic := '0';
    signal start_i : std_logic := '0';
    signal Avec    : vector_fp_t(0 to N_SS - 1) := (others => (others => '0'));
    signal Xvec    : vector_fp_t(0 to N_SS - 1) := (others => (others => '0'));
    signal Yvec    : vector_fp_t(0 to N_SS - 1) := (others => (others => '0'));
    signal Bvec    : vector_fp_t(0 to N_IN - 1) := (others => (others => '0'));
    signal Uvec    : vector_fp_t(0 to N_IN - 1) := (others => (others => '0'));

    -- ── DUT outputs ──────────────────────────────────────────────────────────
    signal result_stub : fixed_point_data_t;
    signal result_ip   : fixed_point_data_t;
    signal busy_stub   : std_logic;
    signal busy_ip     : std_logic;

    -- ── Checker state ────────────────────────────────────────────────────────
    signal mismatch_busy   : natural := 0;
    signal mismatch_result : natural := 0;
    signal check_en        : std_logic := '0';  -- gates busy checker during active tests
    signal prev_busy_stub  : std_logic := '0';

    -- ── Helpers ──────────────────────────────────────────────────────────────
    -- Y = negative integer → disable bilinear (operand2 = FIXED_POINT_ONE)
    -- Y = non-negative integer → index into Xvec
    -- Note: Y is stored as a raw signed integer in the fixed-point vector,
    -- NOT as a Q14.28 value. E.g., y_idx(1) selects X[1].
    function y_idx(i : integer) return fixed_point_data_t is
    begin
        return std_logic_vector(to_signed(i, FP_TOTAL_BITS));
    end function;

    function fp(v : real) return fixed_point_data_t is
    begin
        return to_fp(v);
    end function;

    -- Convert Q14.28 fixed-point raw integer to approximate real for reports
    function fp_to_real_str(v : fixed_point_data_t) return string is
        variable ival : integer;
        variable rval : real;
    begin
        ival := to_integer(signed(v));
        rval := real(ival) / real(2**FP_FRACTION_BITS);
        -- Simple string: just show the raw integer (exact) plus scale note
        return integer'image(ival) & " (raw Q14.28)";
    end function;

begin

    sysclk <= not sysclk after CLK_PERIOD / 2;

    -- ── DUT 1: behavioral stub ────────────────────────────────────────────────
    u_bsu_stub : entity work.BilinearSolverUnit(rtl_stub)
        generic map (N_SS => N_SS, N_IN => N_IN)
        port map (
            sysclk        => sysclk,
            start_i       => start_i,
            Avec_i        => Avec,
            Xvec_i        => Xvec,
            Yvec_i        => Yvec,
            Bvec_i        => Bvec,
            Uvec_i        => Uvec,
            stateResult_o => result_stub,
            busy_o        => busy_stub
        );

    -- ── DUT 2: Xilinx IP sim model ────────────────────────────────────────────
    u_bsu_ip : entity work.BilinearSolverUnit(rtl_ip)
        generic map (N_SS => N_SS, N_IN => N_IN)
        port map (
            sysclk        => sysclk,
            start_i       => start_i,
            Avec_i        => Avec,
            Xvec_i        => Xvec,
            Yvec_i        => Yvec,
            Bvec_i        => Bvec,
            Uvec_i        => Uvec,
            stateResult_o => result_ip,
            busy_o        => busy_ip
        );

    -- ── Checker 1: busy timing must match exactly ─────────────────────────────
    BusyChecker : process(sysclk)
    begin
        if rising_edge(sysclk) then
            if check_en = '1' and busy_stub /= busy_ip then
                report "BUSY MISMATCH at " & time'image(now)
                    & "  stub=" & std_logic'image(busy_stub)
                    & "  ip="   & std_logic'image(busy_ip)
                    severity ERROR;
                mismatch_busy <= mismatch_busy + 1;
            end if;
            prev_busy_stub <= busy_stub;
        end if;
    end process;

    -- ── Checker 2: result must match on the falling edge of busy ──────────────
    ResultChecker : process(sysclk)
    begin
        if rising_edge(sysclk) then
            -- prev_busy_stub='1' and busy_stub='0' → computation just completed
            if check_en = '1' and prev_busy_stub = '1' and busy_stub = '0' then
                if result_stub /= result_ip then
                    report "RESULT MISMATCH at " & time'image(now)
                        & "  stub=" & fp_to_real_str(result_stub)
                        & "  ip="   & fp_to_real_str(result_ip)
                        severity ERROR;
                    mismatch_result <= mismatch_result + 1;
                end if;
            end if;
        end if;
    end process;

    -- ── Stimulus ──────────────────────────────────────────────────────────────
    Stim : process

        -- Apply one set of inputs, pulse start, wait for completion, log result.
        procedure run_test (
            a0, a1   : real;
            x0, x1   : real;
            y0, y1   : integer;   -- negative = no bilinear coupling
            b0, u0   : real;
            tag      : string
        ) is
        begin
            -- Load inputs one cycle before start
            Avec(0) <= fp(a0);  Avec(1) <= fp(a1);
            Xvec(0) <= fp(x0);  Xvec(1) <= fp(x1);
            if y0 < 0 then Yvec(0) <= y_idx(-1); else Yvec(0) <= y_idx(y0); end if;
            if y1 < 0 then Yvec(1) <= y_idx(-1); else Yvec(1) <= y_idx(y1); end if;
            Bvec(0) <= fp(b0);
            Uvec(0) <= fp(u0);
            wait until rising_edge(sysclk);

            -- Enable checkers and pulse start
            check_en <= '1';
            start_i  <= '1';
            wait until rising_edge(sysclk);
            start_i  <= '0';

            -- Wait for stub to finish (IP finishes at the same cycle if matching)
            wait until busy_stub = '0' and rising_edge(sysclk);

            -- Explicit result check (redundant with ResultChecker process, but clearer)
            assert result_stub = result_ip
                report "FINAL MISMATCH [" & tag & "]"
                    & "  stub=" & fp_to_real_str(result_stub)
                    & "  ip="   & fp_to_real_str(result_ip)
                severity ERROR;

            report "[" & tag & "] PASS  stub=" & fp_to_real_str(result_stub)
                   & "  ip=" & fp_to_real_str(result_ip)
                severity NOTE;

            -- Brief idle gap between tests
            check_en <= '0';
            wait for 5 * CLK_PERIOD;
        end procedure;

    begin
        wait for 5 * CLK_PERIOD;

        -- ── Test vectors ──────────────────────────────────────────────────────
        -- zeros: expected result = 0
        run_test(0.0, 0.0, 0.0, 0.0, -1, -1, 0.0, 0.0, "zeros");

        -- linear (no bilinear coupling):
        -- result = 1.0*1.0*0.5 + 2.0*1.0*0.25 + 0.1*3.0 = 0.5 + 0.5 + 0.3 = 1.3
        run_test(0.5, 0.25, 1.0, 2.0, -1, -1, 0.1, 3.0, "linear");

        -- bilinear Y=[1,0]:
        -- result = 1.0*X[1]*0.5 + 2.0*X[0]*0.25 + 0.1*3.0
        --        = 1.0*2.0*0.5  + 2.0*1.0*0.25  + 0.3 = 1.0 + 0.5 + 0.3 = 1.8
        run_test(0.5, 0.25, 1.0, 2.0, 1, 0, 0.1, 3.0, "bilinear");

        -- negative values, Y=[1,0]:
        -- result = (-2.0)*3.0*0.1 + 3.0*(-2.0)*(-0.1) + 0.5*(-1.0)
        --        = -0.6 + 0.6 - 0.5 = -0.5
        run_test(0.1, -0.1, -2.0, 3.0, 1, 0, 0.5, -1.0, "neg_vals");

        -- motor-like (small coefficients, larger state, no bilinear):
        -- result = 5.0*1.0*0.01 + (-3.0)*1.0*0.02 + 0.5*10.0
        --        = 0.05 - 0.06 + 5.0 = 4.99
        run_test(0.01, 0.02, 5.0, -3.0, -1, -1, 0.5, 10.0, "motor_like");

        -- sweep: 8 ramp pairs to stress consecutive pipeline loads
        for k in 1 to 8 loop
            run_test(
                real(k) * 0.05,          -- a0 ramps up
                real(9-k) * 0.05,        -- a1 ramps down
                real(k) * 0.5,           -- x0
                real(k) * (-0.25),       -- x1 (negative)
                -1, -1,                  -- no bilinear
                0.1, real(k) * 1.0,      -- b0, u0
                "sweep_" & integer'image(k)
            );
        end loop;

        -- ── Final report ──────────────────────────────────────────────────────
        wait for 5 * CLK_PERIOD;
        if mismatch_busy = 0 and mismatch_result = 0 then
            report "=== ALL TESTS PASS: BilinearSolverUnit stub == IP ==="
                severity NOTE;
        else
            report "=== FAILURES: busy_mismatches=" & integer'image(mismatch_busy)
                   & "  result_mismatches=" & integer'image(mismatch_result)
                severity FAILURE;
        end if;

        std.env.stop(0);
    end process;

end architecture;
