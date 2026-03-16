--! \file		TIM_Solver.vhd
--!
--! \brief      Three-Phase Induction Motor (TIM) - Hardware-in-the-Loop Emulator
--!             This module implements a real-time mathematical model of a three-phase
--!             induction motor for HIL simulation.
--!             
--!             PARAMETERS:
--!             - Stator resistance (Rs)
--!             - Rotor resistance (Rr)
--!             - Stator inductance (Ls)
--!             - Rotor inductance (Lr)
--!             - Mutual inductance (Lm)
--!             - Moment of inertia (J)
--!             - Number of poles
--!
--!             INPUTS:
--!             - Three-phase voltages (Va, Vb, Vc)
--!             - Mechanical load torque
--!
--!             OUTPUTS:
--!             - Three-phase currents (Ialpha, Ibeta)
--!             - Rotor fluxes
--!             - Mechanical speed
--!
--! \author		Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       06-08-2025
--!
--! \version    1.0
--!
--! \copyright	Copyright (c) 2025 - All Rights reserved.
--!
--! \note		Target devices : No specific target
--! \note		Tool versions  : No specific tool
--! \note		Dependencies   : No specific dependencies
--!
--! \ingroup	None
--! \warning	None
--!
--! \note		Revisions:
--!				- 1.0	06-08-2025	<urielcontardi@hotmail.com>
--!				First revision.
--------------------------------------------------------------------------
-- Default libraries
--------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

--------------------------------------------------------------------------
-- User packages
--------------------------------------------------------------------------
use work.BilinearSolverPkg.all;

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity TIM_Solver is
    Generic (
        DATA_WIDTH          : natural := 42;  -- Data width for fixed-point representation
        -- Discretization parameters
        CLOCK_FREQUENCY     : natural := 200e6;        -- Clock frequency
        Ts                  : real    := 100.0e-9;     -- Discretization step
        -- Motor parameters (leakage inductances — total = leakage + mutual)
        rs            : real    := 0.435;         -- Stator resistance
        rr            : real    := 0.2826;        -- Rotor resistance
        ls            : real    := 3.1364e-3;     -- Stator leakage inductance
        lr            : real    := 6.3264e-3;     -- Rotor leakage inductance
        lm            : real    := 109.9442e-3;   -- Mutual inductance
        j             : real    := 0.192;        -- Moment of inertia
        npp           : real    := 2.0           -- Number of pair poles
    );
    Port (
        -- Clock and reset
        sysclk              : in std_logic;
        reset_n             : in std_logic;
        
        -- Input voltages (3-phase ABC)
        va_i                : in std_logic_vector(DATA_WIDTH-1 downto 0);
        vb_i                : in std_logic_vector(DATA_WIDTH-1 downto 0);
        vc_i                : in std_logic_vector(DATA_WIDTH-1 downto 0);
        
        -- Mechanical load torque input
        torque_load_i       : in std_logic_vector(DATA_WIDTH-1 downto 0);
        
        -- Output currents (3-phase ABC)
        ialpha_o            : out std_logic_vector(DATA_WIDTH-1 downto 0);
        ibeta_o             : out std_logic_vector(DATA_WIDTH-1 downto 0);
        
        -- Rotor fluxes (alpha-beta components)
        flux_rotor_alpha_o  : out std_logic_vector(DATA_WIDTH-1 downto 0);
        flux_rotor_beta_o   : out std_logic_vector(DATA_WIDTH-1 downto 0);
        
        -- Mechanical outputs
        speed_mech_o        : out std_logic_vector(DATA_WIDTH-1 downto 0);

        data_valid_o        : out std_logic

    );
End entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
Architecture rtl of TIM_Solver is

    --------------------------------------------------------------------------
    -- Timer Signals
    --------------------------------------------------------------------------
    constant TIMER_STEPS       : natural := natural(real(CLOCK_FREQUENCY)*Ts);
    signal timer_tick          : std_logic;
    
    --------------------------------------------------------------------------
    -- Clarke Transform Signals
    --------------------------------------------------------------------------
    signal va                  : signed(DATA_WIDTH-1 downto 0);
    signal vb                  : signed(DATA_WIDTH-1 downto 0);
    signal vc                  : signed(DATA_WIDTH-1 downto 0);
    signal valpha              : signed(DATA_WIDTH-1 downto 0);
    signal vbeta               : signed(DATA_WIDTH-1 downto 0);
    signal vzero               : signed(DATA_WIDTH-1 downto 0);
    signal clarke_valid        : std_logic;

    --------------------------------------------------------------------------
    -- TIM Constants
    --------------------------------------------------------------------------m
    constant N_SS              : natural := 5;
    constant N_IN              : natural := 3;

    type matrix_t is array(natural range <>, natural range <>) of real;
    type vector_t is array(natural range <>) of real;
    type matrix_Y_t is array(natural range <>, natural range <>) of integer;

    -- Total inductances (leakage + mutual), matching the C model
    constant Ls_total           : real := ls + lm;
    constant Lr_total           : real := lr + lm;

    constant K                 : real := 1.0/(lm*lm - Ls_total*Lr_total);
    constant AMATRIX           : matrix_t(0 to N_SS - 1, 0 to N_SS - 1) := (
        ( -Ts*rr/Lr_total                     , -Ts*npp                                , Ts*lm*rr/Lr_total                              , 0.0                                             , 0.0),
        ( Ts*npp                              , -Ts*rr/Lr_total                        , 0.0                                            , Ts*lm*rr/Lr_total                               , 0.0),
        ( -Ts*lm*rr*K/Lr_total                , -Ts*lm*npp*K                           , Ts*(lm*lm*rr*K/Lr_total + Lr_total*rs*K)       , 0.0                                             , 0.0),
        ( Ts*lm*npp*K                         , -Ts*lm*rr*K/Lr_total                   , 0.0                                            , Ts*(lm*lm*rr*K/Lr_total + Lr_total*rs*K)        , 0.0),
        ( Ts*(3.0*npp*lm)/(2.0*j*Lr_total)    , Ts*(-3.0*npp*lm)/(2.0*j*Lr_total)     , 0.0                                            , 0.0                                             , 0.0)
    );

    -- The Y matrix is only used to allow X states to be multiplied with each other
    -- -1.0 indicates that the entry will not be used, while a positive value can be
    -- configured to indicate which index of X will be multiplied
    constant YMATRIX           : matrix_Y_t(0 to N_SS - 1, 0 to N_SS - 1) := (
        ( -1,  4, -1, -1, -1),
        (  4, -1, -1, -1, -1),
        ( -1,  4, -1, -1, -1),
        (  4, -1, -1, -1, -1),
        (  3,  2, -1, -1, -1)
    );

    constant BMATRIX           : matrix_t(0 to N_SS - 1, 0 to N_IN - 1) := (
        ( 0.0          , 0.0          , 0.0),
        ( 0.0          , 0.0          , 0.0),
        ( -Ts*Lr_total*K, 0.0          , 0.0),
        ( 0.0          , -Ts*Lr_total*K, 0.0),
        ( 0.0          ,  0.0          , -Ts/j)  -- TL/J, division at elaboration time
    );

    --------------------------------------------------------------------------
    -- Conversion Functions
    --------------------------------------------------------------------------
    -- Function to convert matrix_t to matrix_fp_t
    function matrix_to_fp(matrix_real : matrix_t) return matrix_fp_t is
        variable result : matrix_fp_t(matrix_real'range(1), matrix_real'range(2));
    begin
        for i in matrix_real'range(1) loop
            for col in matrix_real'range(2) loop
                result(i, col) := to_fp(matrix_real(i, col));
            end loop;
        end loop;
        return result;
    end function;

    -- Function to convert vector_t to vector_fp_t
    function vector_to_fp(vector_real : vector_t) return vector_fp_t is
        variable result : vector_fp_t(vector_real'range);
    begin
        for i in vector_real'range loop
            result(i) := to_fp(vector_real(i));
        end loop;
        return result;
    end function;

    -- Function to convert matrix_Y_t to matrix_fp_t (special handling for Y matrix)
    function matrix_Y_to_fp(matrix_int : matrix_Y_t) return matrix_fp_t is
        variable result : matrix_fp_t(matrix_int'range(1), matrix_int'range(2));
        variable temp_unsigned : unsigned(FP_TOTAL_BITS - 1 downto 0);
    begin
        for i in matrix_int'range(1) loop
            for col in matrix_int'range(2) loop
                if matrix_int(i, col) < 0 then
                    -- If negative, set MSB to '1' and all other bits to '0'
                    result(i, col) := (FP_TOTAL_BITS - 1 => '1', others => '0');
                else
                    -- If positive, convert to unsigned representation
                    temp_unsigned := to_unsigned(matrix_int(i, col), FP_TOTAL_BITS);
                    result(i, col) := std_logic_vector(temp_unsigned);
                end if;
            end loop;
        end loop;
        return result;
    end function;

    --------------------------------------------------------------------------
    -- TIM Signals
    --------------------------------------------------------------------------
    constant Amatrix_fp     : matrix_fp_t(0 to N_SS - 1, 0 to N_SS - 1) := matrix_to_fp(AMATRIX);
    constant Ymatrix_fp     : matrix_fp_t(0 to N_SS - 1, 0 to N_SS - 1) := matrix_Y_to_fp(YMATRIX);
    constant Bmatrix_fp     : matrix_fp_t(0 to N_SS - 1, 0 to N_IN - 1) := matrix_to_fp(BMATRIX);
    signal Xvec_fp          : vector_fp_t(0 to N_SS - 1);
    signal dXvec_fp         : vector_fp_t(0 to N_SS - 1);
    signal Uvec_fp          : vector_fp_t(0 to N_IN - 1);
    signal solver_busy      : std_logic;
    signal solver_done      : std_logic;

Begin

    --------------------------------------------------------------------------
    -- Synthesis Verification
    --------------------------------------------------------------------------
    assert DATA_WIDTH = FP_TOTAL_BITS
        report "DATA_WIDTH must be equal to FP_TOTAL_BITS"
        severity FAILURE;

    -- Ensure CLOCK_FREQUENCY * Ts is an integer
    assert real(TIMER_STEPS) = real(CLOCK_FREQUENCY) * Ts
        report "CLOCK_FREQUENCY * Ts must be an integer value"
        severity FAILURE;

    --------------------------------------------------------------------------
    -- Discretization Timer 
    --------------------------------------------------------------------------
    Timer_Inst : process(sysclk, reset_n)
        variable timer_counter : natural range 0 to TIMER_STEPS - 1;
    begin
        if reset_n = '0' then
            timer_counter   := 0;
            timer_tick      <= '0';
        elsif rising_edge(sysclk) then
            if timer_counter = TIMER_STEPS - 1 then
                timer_counter   := 0;
                timer_tick      <= '1';
            else
                timer_counter := timer_counter + 1;
                timer_tick      <= '0';
            end if;
        end if;
    end process;

    --------------------------------------------------------------------------
    -- Clarke Transform Instance
    --------------------------------------------------------------------------
    ClarkeTransform_Inst : Entity work.ClarkeTransform
    Generic map(
        DATA_WIDTH      => FP_TOTAL_BITS,
        FRAC_WIDTH      => FP_FRACTION_BITS
    )
    Port map(
        sysclk          => sysclk,
        reset_n         => reset_n,
        data_valid_i    => timer_tick,
        a_in            => va,
        b_in            => vb,
        c_in            => vc,
        --  Alpha-Beta Output (two's complement, fixed point)
        alpha_o         => valpha,
        beta_o          => vbeta,
        zero_o          => vzero,
        data_valid_o    => clarke_valid
    );

    va <= signed(va_i);
    vb <= signed(vb_i);
    vc <= signed(vc_i);

    --------------------------------------------------------------------------
    -- Bilinear Solver Handler Instance
    --------------------------------------------------------------------------
    TIMSolverHandler_Inst : Entity work.BilinearSolverHandler
    Generic map(
        N_SS                => N_SS,
        N_IN                => N_IN
    )
    Port map(
        sysclk              => sysclk,
        start_i             => clarke_valid and not solver_busy,
        Amatrix_i           => Amatrix_fp,
        Xvec_i              => Xvec_fp,
        Ymatrix_i           => Ymatrix_fp,
        Bmatrix_i           => Bmatrix_fp,
        Uvec_i              => Uvec_fp,
        stateResultVec_o    => dXvec_fp,
        busy_o              => solver_busy
    );

    -- Convert input signals to Uvec_fp
    Uvec_fp(0) <= std_logic_vector(valpha);
    Uvec_fp(1) <= std_logic_vector(vbeta);
    Uvec_fp(2) <= torque_load_i;

    --------------------------------------------------------------------------
    -- Discretization
    -- x[k+1] = x[k] + dX[k]
    --------------------------------------------------------------------------
    CalcDone_Inst : Entity work.EdgeDetector
    Generic map(
        EDGE     => '0'
    )
    Port map(
        sysclk   => sysclk,
        reset_n  => reset_n,
        signal_i => solver_busy,
        tick_o   => solver_done
    );

    Euler : process (sysclk)
    begin
        if reset_n = '0' then
            Xvec_fp      <= (others => (others => '0'));
            data_valid_o <= '0';
        elsif rising_edge(sysclk) then

            data_valid_o <= '0';
            if solver_done = '1' then
                data_valid_o <= '1';
                for i in 0 to N_SS - 1 loop
                    Xvec_fp(i) <= std_logic_vector(signed(Xvec_fp(i)) + signed(dXvec_fp(i)));
                end loop;
            end if;
    
        end if;
    end process;

    --------------------------------------------------------------------------
    -- Output Assignments
    -- Xvec_fp(0) = ψ_rα (rotor flux alpha)
    -- Xvec_fp(1) = ψ_rβ (rotor flux beta)
    -- Xvec_fp(2) = i_sα (stator current alpha)
    -- Xvec_fp(3) = i_sβ (stator current beta)
    -- Xvec_fp(4) = ω_m  (mechanical speed)
    --------------------------------------------------------------------------
    ialpha_o            <= Xvec_fp(2);
    ibeta_o             <= Xvec_fp(3);
    flux_rotor_alpha_o  <= Xvec_fp(0);
    flux_rotor_beta_o   <= Xvec_fp(1);
    speed_mech_o        <= Xvec_fp(4);

End architecture;
