--! \file		StateSpaceSolver.vhd
--!
--! \brief      XdVec = AMatrix_i * XVec + BMatrix_i * UVec_i
--!
--! \author		Uriel Abe Contardi (urielcontardi@hotmail.com)
--! \date       03-06-2024
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
--!				- 1.0	03-06-2024	<urielcontardi@hotmail.com>
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
Entity StateSpaceSolver is
    Generic (
        N_SS    : natural := 5;    -- Number of State Space
        N_IN    : natural := 2     -- Inputs number of State Space
    );
    Port (
        sysclk      : in std_logic;

        -- Interface
        start_i     : in std_logic;
        busy_o      : out std_logic;

        -- Vector Inputs
        UVec_i      : in vector_fp_t(0 to N_IN - 1);

        -- Coefficients
        AMatrix_i   : in matrix_fp_t(0 to N_SS - 1, 0 to N_SS - 1);
        BMatrix_i   : in matrix_fp_t(0 to N_SS - 1, 0 to N_IN - 1);

        -- Vector Outputs 
        XVec_o      : out vector_fp_t(0 to N_SS - 1)

    );
End entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
Architecture rtl of StateSpaceSolver is
    
    -- Constant
    constant RESET_DELAY_CYCLES : integer := 50;
    
    -- State Space Vector
    type AVec_t is array (0 to N_SS - 1) of vector_fp_t(0 to N_SS - 1);
    type BVec_t is array (0 to N_SS - 1) of vector_fp_t(0 to N_IN - 1);

    signal XdVec        : vector_fp_t(0 to N_SS - 1) := (others => (others => '0')); -- Differential state vector
    signal AVec         : AVec_t;
    signal XVec         : vector_fp_t(0 to N_SS - 1) := (others => (others => '0')); -- State Vector
    signal BVec         : BVec_t;
    signal UVec         : vector_fp_t(0 to N_IN - 1) := (others => (others => '0'));

    -- Control Signals
    signal startCalc    : std_logic := '0';
    signal busyVec      : std_logic_vector(N_SS - 1 downto 0);
    signal busy         : std_logic;

    --------------------------------------------------------------------------
    -- Functions
    --------------------------------------------------------------------------
    function getRowMatrix(
        matrix   : matrix_fp_t; 
        rowIndex : natural
    ) return vector_fp_t is
        variable rowData : vector_fp_t(matrix'range(2)); 
    begin
   
        -- Itera sobre o intervalo de colunas
        for colIndex in matrix'range(2) loop
            rowData(colIndex) := matrix(rowIndex, colIndex);
        end loop;
        
        return rowData;
    end function;

Begin

    --------------------------------------------------------------------------
    -- Assign Output
    --------------------------------------------------------------------------
    busy_o <= busy;
    XVec_o <= XdVec;

    --------------------------------------------------------------------------
    -- State Space Solver Instantiation
    --------------------------------------------------------------------------
    StateSolverGen : for aa in 0 to N_SS - 1 generate

        AVec(aa) <= getRowMatrix(AMatrix_i, aa);
        BVec(aa) <= getRowMatrix(BMatrix_i, aa);

        SolverStateInst: Entity work.StateSolver
        Generic map(
            N_SS    => N_SS,
            N_IN    => N_IN
        )
        Port map(
            sysclk      => sysclk,
            -- Interface
            valid_i     => startCalc,
            busy_o      => busyVec(aa),
            -- Inputs
            AVec_i     => AVec(aa),
            XVec_i     => XVec,
            BVec_i     => BVec(aa),
            UVec_i     => UVec,
            -- State Result
            XdVec_o    => XdVec(aa)
        ); 

    End generate;

    busy <= '1' when busyVec /= (busyVec'range => '0') else '0';

    --------------------------------------------------------------------------
    -- Control Process
    --------------------------------------------------------------------------
    StateDelay : process (sysclk)
        variable reset_ctr  : integer := 0;
    begin
        if rising_edge(sysclk) then

            if reset_ctr < RESET_DELAY_CYCLES then
                reset_ctr := reset_ctr + 1;
                startCalc <= '1';
            elsif start_i = '1' AND busy = '0' then
                UVec        <= UVec_i;
                XVec        <= XdVec;
                startCalc   <= '1';
            else
                startCalc <= '0';
            end if;
    
        end if;
    end process;
    

End architecture;
