--! \file		MIT_SolverUnit.vhd
--!
--! \brief		stateResult_o = A * X * Y + B * U
--!
--!             In this case, Y acts as a selector for the state vector X.
--!             This allows the solver to multiply two different state variables,
--!             enabling more flexible state-space computations.
--!
--!             If Y is not used, it can be set to a negative value (e.g., -1) to
--!             indicate that it should not be considered in the multiplication.
--!
--! \author		Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       31-07-2025
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
--!				- 1.0	31-07-2025	<urielcontardi@hotmail.com>
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
use work.MIT_Pkg.all;

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity MIT_SolverUnit is
    Generic (
        N_SS    : natural := 5;    -- Number of State Space
        N_IN    : natural := 2     -- Inputs number of State Space
    );
    Port (
        sysclk          : in std_logic;
        start_i         : in std_logic;

        Avec_i          : in vector_fp_t(0 to N_SS - 1);
        Xvec_i          : in vector_fp_t(0 to N_SS - 1);
        Yvec_i          : in vector_fp_t(0 to N_SS - 1);

        Bvec_i          : in vector_fp_t(0 to N_IN - 1);
        Uvec_i          : in vector_fp_t(0 to N_IN - 1);

        stateResult_o   : out fixed_point_data_t;
        busy_o          : out std_logic
    );
End entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
Architecture rtl of MIT_SolverUnit is

    constant TOTAL_OPERATIONS   : integer := N_SS+N_IN;
    constant MULTIPLIER_DELAY   : integer := 7;
    constant FIXED_POINT_ONE    : fixed_point_data_t := std_logic_vector(to_signed(2**FP_FRACTION_BITS, FP_TOTAL_BITS));

    -- Handle Input to do logic
    signal operand1_vec         : vector_fp_t(0 to TOTAL_OPERATIONS - 1);
    signal operand2_vec         : vector_fp_t(0 to TOTAL_OPERATIONS - 1);
    signal operand3_vec         : vector_fp_t(0 to TOTAL_OPERATIONS - 1) := (others => FIXED_POINT_ONE);
    signal operand1             : fixed_point_data_t;
    signal operand2             : fixed_point_data_t;
    signal operand3             : fixed_point_data_t;

    -- Sequencer
    signal pipeline1            : std_logic_vector(MULTIPLIER_DELAY - 1 downto 0) := (others => '0');
    signal pipeline2            : std_logic_vector(MULTIPLIER_DELAY - 1 downto 0) := (others => '0');
    signal index1               : integer range 0 to TOTAL_OPERATIONS;
    signal index2               : integer range 0 to TOTAL_OPERATIONS;
    signal pipeline3_tgr        : std_logic := '0';
    signal busy                 : std_logic := '0';

    -- Multiplier Signals
    signal product1_raw         : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0);
    signal product1             : fixed_point_data_t;
    signal product2_raw         : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0);

    -- Accumulator
    signal acmtr                : std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0) := (others => '0');

    --------------------------------------------------------------------------
    -- Component Declaration
    -- Note: This component is a DSP48 IP core from Xilinx
    --------------------------------------------------------------------------
    component MIT_SolverUnit_DSP
    port (
        CLK : in std_logic;
        A   : in std_logic_vector(FP_TOTAL_BITS - 1 downto 0);
        B   : in std_logic_vector(FP_TOTAL_BITS - 1 downto 0);
        P   : out std_logic_vector((2*FP_TOTAL_BITS)-1 downto 0)
    );
    end component;

Begin

    --------------------------------------------------------------------------
    -- Assign Output
    --------------------------------------------------------------------------
    stateResult_o <= acmtr(FP_TOTAL_BITS + FP_FRACTION_BITS - 1 downto FP_FRACTION_BITS);
    busy_o        <= busy;

    --------------------------------------------------------------------------
    -- Internal Signals
    --------------------------------------------------------------------------
    operand1_vec(0 to N_SS - 1)  <= Avec_i;
    operand1_vec(N_SS to TOTAL_OPERATIONS - 1) <= Bvec_i;

    operand2_vec(0 to N_SS - 1)  <= Xvec_i;
    operand2_vec(N_SS to TOTAL_OPERATIONS - 1) <= Uvec_i;

    YVec : process (Yvec_i)
        variable index : integer range 0 to N_SS - 1;
    begin
        for aa in 0 to N_SS - 1 loop

            -- If Y is not used, set it to a negative value (e.g., -1)
            -- This will effectively ignore the Y vector in the multiplication.
            if Yvec_i(aa)(FP_TOTAL_BITS - 1) = '1' then
                operand3_vec(aa) <= FIXED_POINT_ONE;
            else
                index := to_integer(signed(Yvec_i(aa)));
                operand3_vec(aa) <= Xvec_i(index);
            end if;
        end loop;
    end process;

    -- We need these elements just to keep a cleaner architecture
    -- In this case, we fill with the value FIXED_POINT_ONE so that it does not
    -- influence the multiplication of Bvec_i and Uvec_i
    gen_operand3 : for i in N_SS to TOTAL_OPERATIONS - 1 generate
        operand3_vec(i) <= FIXED_POINT_ONE;
    end generate;
    
    --------------------------------------------------------------------------
    -- Multiplier
    --------------------------------------------------------------------------
    Multiplier1 : MIT_SolverUnit_DSP
    port map (
        CLK => sysclk,
        A => operand1,
        B => operand2,
        P => product1_raw
    );
    
    operand1    <= operand1_vec(index1);
    operand2    <= operand2_vec(index1);
    product1    <= product1_raw(FP_TOTAL_BITS + FP_FRACTION_BITS - 1 downto FP_FRACTION_BITS);
    
    Multiplier2 : MIT_SolverUnit_DSP
    port map (
        CLK => sysclk,
        A => product1,
        B => operand3,
        P => product2_raw
    );

    operand3    <= operand3_vec(index2);

    --------------------------------------------------------------------------
    -- Sequencer
    --------------------------------------------------------------------------
    process(sysclk)
        variable pipeline1_tgr  : std_Logic := '0';
        variable pipeline2_tgr  : std_Logic := '0';
    begin
        if rising_edge(sysclk) then
            
            --------------------------------------------------------------------------
            -- Pipeline Trigger
            --------------------------------------------------------------------------
            if start_i = '1' and busy = '0' then
                pipeline1_tgr   := '1';
            elsif index1 = TOTAL_OPERATIONS - 1 then
                pipeline1_tgr   := '0';
            end if;

            --------------------------------------------------------------------------
            -- 1. First pipeline stage
            -- operand1 and operand2 multiplication
            --------------------------------------------------------------------------
            -- Pipeline
            pipeline1 <= pipeline1(pipeline1'left - 1 downto 0) & pipeline1_tgr;

            if pipeline1(pipeline1'right) = '1' AND index1 < TOTAL_OPERATIONS - 1 then
                index1 <= index1 + 1;
            else
                index1 <= 0;
            end if;
            
            --------------------------------------------------------------------------
            -- 2. Second pipeline stage
            -- product1 and operand3 multiplication
            --------------------------------------------------------------------------
            pipeline2_tgr := pipeline1(pipeline1'left);
            pipeline2 <= pipeline2(pipeline2'left - 1 downto 0) & pipeline2_tgr;

            if pipeline2(pipeline2'right) = '1' AND index2 < TOTAL_OPERATIONS - 1 then
                index2 <= index2 + 1;
            else
                index2 <= 0;
            end if;
            
            --------------------------------------------------------------------------
            -- 3. Third stage: Accumulator
            --------------------------------------------------------------------------
            pipeline3_tgr <= pipeline2(pipeline2'left);
            if start_i = '1' and busy = '0' then
                acmtr <= (others => '0');
            elsif pipeline3_tgr = '1' then
                acmtr <= std_logic_vector(signed(acmtr) + signed(product2_raw));
            end if;

            --------------------------------------------------------------------------
            -- Busy Signal
            --------------------------------------------------------------------------
            if start_i = '1' then
                busy <= '1';
            elsif  pipeline1 = (pipeline1'range => '0') AND
                    pipeline2 = (pipeline2'range => '0') AND
                    pipeline3_tgr = '0' then
                busy <= '0';
            end if;

        end if;
    end process;

End architecture;
