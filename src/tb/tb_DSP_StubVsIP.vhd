--! \file       tb_DSP_StubVsIP.vhd
--!
--! \brief      Side-by-side comparison: BilienarSolverUnit_DSP stub vs Xilinx IP.
--!
--!             Both implementations share the same entity name but different
--!             architecture names, allowing direct instantiation in one TB:
--!               DUT_STUB → entity work.BilienarSolverUnit_DSP(behavior)
--!               DUT_IP   → entity work.BilienarSolverUnit_DSP(bilienarsolverunit_dsp_arch)
--!
--!             The same input vectors are driven to both. Their outputs are
--!             compared cycle-by-cycle after the pipeline fills (7 cycles).
--!             A single mismatch triggers FAILURE and stops simulation.
--!
--!             Run via:  make sim-dsp-compare
--!             Requires: Vivado project created (make vivado-project)
--!             Fileset:  sim_compare  (stub + IP sim model both available)
--!
--! \author     Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       04-04-2026
--------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.BilinearSolverPkg.all;

entity tb_DSP_StubVsIP is
end entity;

architecture sim of tb_DSP_StubVsIP is

    constant LATENCY    : natural := 7;
    constant CLK_PERIOD : time    := 10 ns;
    constant W          : natural := FP_TOTAL_BITS;  -- 42

    signal clk    : std_logic := '0';
    signal A      : std_logic_vector(W-1 downto 0) := (others => '0');
    signal B      : std_logic_vector(W-1 downto 0) := (others => '0');
    signal P_stub : std_logic_vector(2*W-1 downto 0);
    signal P_ip   : std_logic_vector(2*W-1 downto 0);

    -- Max 42-bit signed positive: MSB=0, rest=1
    constant MAX_POS : std_logic_vector(W-1 downto 0) := (W-1 => '0', others => '1');

    signal fill_done : std_logic := '0';
    signal clk_count : natural   := 0;
    signal mismatch  : natural   := 0;

begin

    clk <= not clk after CLK_PERIOD / 2;

    -- ── DUT 1: behavioral stub (used in GHDL/NVC simulation) ─────────────────
    DUT_STUB : entity work.BilienarSolverUnit_DSP(behavior)
        port map (CLK => clk, A => A, B => B, P => P_stub);

    -- ── DUT 2: Xilinx mult_gen IP sim model (DSP48E1 behavioral) ─────────────
    DUT_IP : entity work.BilienarSolverUnit_DSP(bilienarsolverunit_dsp_arch)
        port map (CLK => clk, A => A, B => B, P => P_ip);

    -- ── Clock counter ─────────────────────────────────────────────────────────
    process(clk)
    begin
        if rising_edge(clk) then
            clk_count <= clk_count + 1;
            if clk_count >= LATENCY then
                fill_done <= '1';
            end if;
        end if;
    end process;

    -- ── Checker: compare cycle-by-cycle after pipeline fills ─────────────────
    process(clk)
    begin
        if rising_edge(clk) then
            if fill_done = '1' then
                if P_stub /= P_ip then
                    report "MISMATCH at " & time'image(now)
                        severity FAILURE;
                    mismatch <= mismatch + 1;
                end if;
            end if;
        end if;
    end process;

    -- ── Stimulus ──────────────────────────────────────────────────────────────
    Stim : process

        procedure apply(
            a_vec : in std_logic_vector(W-1 downto 0);
            b_vec : in std_logic_vector(W-1 downto 0);
            tag   : in string
        ) is
        begin
            A <= a_vec;
            B <= b_vec;
            for i in 0 to LATENCY loop
                wait until rising_edge(clk);
            end loop;
            -- Both DUTs have settled — checker already verified match above.
            -- Report vector name so the waveform has visible markers.
            report "Vector done: [" & tag & "]" severity NOTE;
        end procedure;

        function fp(v : real) return std_logic_vector is
        begin return to_fp(v); end function;

    begin
        wait for 5 * CLK_PERIOD;

        -- 1. Zero
        apply((others => '0'), (others => '0'), "0*0");

        -- 2. Raw 1 × 1
        apply(std_logic_vector(to_signed(1, W)),
              std_logic_vector(to_signed(1, W)), "1*1");

        -- 3. Q14.28  1.0 × 1.0
        apply(fp(1.0), fp(1.0), "1.0*1.0");

        -- 4. Q14.28 -1.0 × 1.0
        apply(fp(-1.0), fp(1.0), "-1.0*1.0");

        -- 5. Q14.28 -1.0 × -1.0
        apply(fp(-1.0), fp(-1.0), "-1.0*-1.0");

        -- 6. Q14.28  0.5 × 2.0
        apply(fp(0.5), fp(2.0), "0.5*2.0");

        -- 7. Typical motor: 5.0 A × 0.123 coefficient
        apply(fp(5.0), fp(0.123), "5A*0.123");

        -- 8. Mixed sign
        apply(fp(5.0), fp(-0.123), "5A*-0.123");

        -- 9. Max positive × 1
        apply(MAX_POS, std_logic_vector(to_signed(1, W)), "MAX*1");

        -- 10. Max positive × max positive
        apply(MAX_POS, MAX_POS, "MAX*MAX");

        -- 11. Large sweep: ramp A, fixed B — stresses consecutive pipeline loads
        for k in 1 to 16 loop
            apply(fp(real(k) * 0.5),
                  fp(real(17 - k) * 0.25),
                  "ramp_" & integer'image(k));
        end loop;

        -- Done
        wait for 5 * CLK_PERIOD;

        if mismatch = 0 then
            report "=== ALL VECTORS MATCH: stub == IP ===" severity NOTE;
        else
            report "=== " & integer'image(mismatch) & " MISMATCH(ES) ===" severity FAILURE;
        end if;

        std.env.stop(0);
    end process;

end architecture;
