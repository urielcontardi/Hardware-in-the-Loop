--! \file		MIT_Pkg.vhd
--!
--! \brief		Packages for the MIT Solver
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
Library ieee;
Use ieee.std_logic_1164.all;
Use ieee.numeric_std.all;
use ieee.math_real.all;

--------------------------------------------------------------------------
-- User packages
--------------------------------------------------------------------------

--------------------------------------------------------------------------
-- Package
--------------------------------------------------------------------------
Package MIT_Pkg is
    
    --------------------------------------------------------------------------
    -- Constants
    --------------------------------------------------------------------------
    constant FP_INTEGER_BITS          : natural := 14;     
    constant FP_FRACTION_BITS         : natural := 28;     
    constant FP_TOTAL_BITS            : integer := FP_INTEGER_BITS + FP_FRACTION_BITS;

    subtype fixed_point_data_t is std_logic_vector(FP_TOTAL_BITS - 1 downto 0);
    type vector_fp_t is array (natural range <>) of fixed_point_data_t;
    type matrix_fp_t is array(natural range <>, natural range <>) of fixed_point_data_t;
    
    --------------------------------------------------------------------------
    -- Functions | Procedures
    --------------------------------------------------------------------------
    function to_fp (val : real) return fixed_point_data_t; 

End package;

Package body MIT_Pkg is

    --------------------------------------------------------------------------
    -- to_fp
    --------------------------------------------------------------------------
    function to_fp (val : real) return fixed_point_data_t is
        constant SCALE          : real      := 2.0 ** FP_FRACTION_BITS;
        variable int_val        : real;
        variable result         : std_logic_vector(FP_TOTAL_BITS - 1 downto 0);
        variable is_negative    : boolean;
        variable abs_val        : real;
        variable temp_val       : real;
        variable bit_weight     : real;
    begin
        int_val := val * SCALE;
        
        -- Check if the value is negative
        is_negative := int_val < 0.0;
        abs_val := abs(int_val);
        
        -- Initialize result
        result := (others => '0');
        
        -- Convert absolute value to binary
        temp_val := abs_val;
        for i in FP_TOTAL_BITS - 2 downto 0 loop
            bit_weight := 2.0 ** i;
            if temp_val >= bit_weight then
                result(i) := '1';
                temp_val := temp_val - bit_weight;
            end if;
        end loop;
        
        -- Apply two's complement if negative
        if is_negative then
            -- Invert all bits
            for i in result'range loop
                result(i) := not result(i);
            end loop;
            
            -- Add 1 (two's complement)
            for i in 0 to FP_TOTAL_BITS - 1 loop
                if result(i) = '0' then
                    result(i) := '1';
                    exit;
                else
                    result(i) := '0';
                end if;
            end loop;
        end if;

        return result;
        
    end function to_fp;
    
End package body;