--! \file		StateSpaceSolver.vhd
--!
--! \brief		
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
    generic (
        N_SS    : natural := 5;    -- Number of State Space
        N_IN    : natural := 2     -- Inputs number of State Space
    );
    Port (
        sysclk  : in std_logic;
        reset_n : in std_logic;
        start_i : in std_logic;

        -- Interface to load Matrix
        -- addr_i      : in std_logc;
        -- sel_ab_i    : in std_logic
    );
End entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
Architecture rtl of StateSpaceSolver is
    
    signal A_matrix : matrix_t(0 to N_SS - 1; 0 to N_SS - 1);
    signal B_matrix : matrix_t(0 to N_SS - 1; 0 to N_IN - 1);
    signal state_vector : state_vector_t(0 to N_SS - 1);

Begin

End architecture;
