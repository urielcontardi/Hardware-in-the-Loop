--! \file		StateSolver.vhd
--!
--! \brief		
--!
--! \author		Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       23-06-2024
--!
--! \version    1.0
--!
--! \copyright	Copyright (c) 2024 - All Rights reserved.
--!
--! \note		Target devices : No specific target
--! \note		Tool versions  : No specific tool
--! \note		Dependencies   : No specific dependencies
--!
--! \ingroup
--! \warning	None
--!
--! \note		Revisions:
--!				- 1.0	23-06-2024	<urielcontardi@hotmail.com>
--!				First revision.
--------------------------------------------------------------------------
-- Default libraries
--------------------------------------------------------------------------
Library ieee;
Use ieee.std_logic_1164.all;
Use ieee.numeric_std.all;

--------------------------------------------------------------------------
-- User packages
--------------------------------------------------------------------------
use work.Solver_pkg.all;

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity StateSolver is
    Generic (
        N_SS    : natural := 5;    -- Number of State Space
        N_IN    : natural := 2     -- Inputs Number of State Space
    );
    Port (
        sysclk      : in std_logic;
        reset_n     : in std_logic;
        -- Interface
        valid_i     : in std_logic;
        busy_o      : out std_logic
        -- Inputs
        a_vec_i     : in vector_fp_t(0 to N_SS - 1);
        x_vec_i     : in vector_fp_t(0 to N_SS - 1);
        b_vec_i     : in vector_fp_t(0 to N_IN - 1);
        u_vec_i     : in vector_fp_t(0 to N_IN - 1);
        -- State Result
        state_o    : out fixed_point_data_t;
    );
End entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
Architecture rtl of StateSolver is
    
    -- Constants
    constant TOTAL_OPERATIONS   : integer := N_SS+N_IN;
    constant MULTIPLIER_DELAY   : integer := 6;

    -- Sequencer
    signal index                : integer range 0 to TOTAL_OPERATIONS;
    signal data_valid           : std_logic := '0';

    -- Pipeline
    signal pipeline             : std_logic_vector(MULTIPLIER_DELAY - 1 downto 0);

    -- Multiplier Signals
    signal aVector, bVector     : vector_fp_t(0 to N_SS + N_IN - 1);
    signal aFactor, bFactor   : fixed_point_data_t;
    signal product              : std_logic_vector(63 downto 0);
    
    -- Accumulator
    signal result                : std_logic_vector(63 downto 0) := (others => '0');

    --------------------------------------------------------------------------
    -- Components
    --------------------------------------------------------------------------
    component StateSolverMultiplier
    port (
      CLK   : in STD_LOGIC;
      A     : in STD_LOGIC_VECTOR(31 downto 0);
      B     : in STD_LOGIC_VECTOR(31 downto 0);
      P     : out STD_LOGIC_VECTOR(63 downto 0)
    );
    end component;

Begin

    --------------------------------------------------------------------------
    -- Assign Output
    --------------------------------------------------------------------------
    busy_o      <= '1' when pipeline /= (pipeline'range => '0') else '0';
    result_o    <= result(result_o'range);

    --------------------------------------------------------------------------
    -- Multiplier
    -- Note: DSP48 Xilinx IP, optimum pipeline 6
    --------------------------------------------------------------------------
    Multiplier : StateSolverMultiplier
    port map (
        CLK => sysclk,
        A => aFactor,
        B => bFactor,
        P => product
    );

    aFactor    <= aVector(index);
    bFactor    <= bVector(index);

    -- Concatenate a_vec_i with b_vec_i and x_vec_i with u_vec_i to facilitate
    -- calculations. This allows for more efficient code
    aVector <= a_vec_i & b_vec_i;
    bVector <= x_vec_i & u_vec_i;
    
    --------------------------------------------------------------------------
    -- Sequencer
    --------------------------------------------------------------------------
    process(sysclk)
    begin
        if rising_edge(sysclk) then

                --------------------------------------------------------------------------
                -- Sequencer
                -- Responsible for feeding the multiplier and iterating over all the data 
                -- that needs to be multiplied
                --------------------------------------------------------------------------
                data_valid <= '0';
                if index < TOTAL_OPERATIONS - 1 then
                    index <= index + 1;
                    data_valid <= '1';
                elsif init_i = '1' then
                    index <= 0;
                    data_valid <= '1';
                end if;

                --------------------------------------------------------------------------
                -- Pipeline Multiplier
                -- The multiplier has a delay of MULTIPLIER_DELAY and pipeline
                -- mechanism is used to feed the data.
                --------------------------------------------------------------------------
                pipeline <= pipeline(pipeline'left - 1 downto 0) & data_valid;

                --------------------------------------------------------------------------
                -- Accumulator
                -- The multiplier will have valid data after the delay of MULTIPLIER_DELAY.
                -- Therefore, each term is added to the previously multiplied.
                --------------------------------------------------------------------------
                if init_i = '1' then
                    result <= (others => '0');
                elsif pipeline(pipeline'left) = '1' then
                    result <= std_logic_vector(signed(result) + signed(product));
                end if;
                    
        end if;
    end process;

End architecture;
