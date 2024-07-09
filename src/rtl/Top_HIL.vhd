--! \file		Top_HIL.vhd
--!
--! \brief		
--!
--! \author		Uriel Abe Contardi (e-uriel@weg.net)
--! \date       16-04-2024
--!
--! \version    1.0
--!
--! \copyright	Copyright (c) 2022 WEG - All Rights reserved.
--!
--! \note		Target devices : No specific target
--! \note		Tool versions  : No specific tool
--! \note		Dependencies   : No specific dependencies
--!
--! \ingroup	WCW
--! \warning	None
--!
--! \note		Revisions:
--!				- 1.0	16-04-2024	<e-uriel@weg.net>
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

--------------------------------------------------------------------------
-- Entity declaration
--------------------------------------------------------------------------
Entity Top_HIL is
    Port (
        sysclk  : in std_logic;
        reset_n : in std_logic;

        
    );
End entity;

--------------------------------------------------------------------------
-- Architecture
--------------------------------------------------------------------------
Architecture rtl of Top_HIL is

Begin

    --------------------------------------------------------------------------
    -- UART
    --------------------------------------------------------------------------
    

end architecture ;
