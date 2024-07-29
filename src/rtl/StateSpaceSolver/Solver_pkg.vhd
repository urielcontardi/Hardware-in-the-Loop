--! \file		Solver_pkg.vhd
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

--------------------------------------------------------------------------
-- Package
--------------------------------------------------------------------------
Package Solver_pkg is
    
    constant M_BITS         : natural := 16;     -- M Bits to Integer Representation
    constant N_BITS         : natural := 16;     -- N Bits to Fraction Representation
    constant FP_TOTAL_BITS  : integer := M_BITS + N_BITS;

    subtype fixed_point_data_t is std_logic_vector(FP_TOTAL_BITS - 1 downto 0);
    type vector_fp_t is array (natural range <>) of fixed_point_data_t;
    type matrix_fp_t is array(natural range <>, natural range <>) of fixed_point_data_t;

End package;