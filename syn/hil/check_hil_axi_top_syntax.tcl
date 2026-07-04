# Syntax-check standalone do HIL_AXI_Top.vhd e dependencias, sem criar um
# projeto Vivado completo nem sintetizar. Usado como teste rapido de
# elaboracao — nao substitui a sintese real (fora de escopo deste plano).
set root_dir "/home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop"
read_vhdl -vhdl2008 $root_dir/common/modules/bilinear_solver/src/BilinearSolverPkg.vhd
read_vhdl -vhdl2008 $root_dir/src/rtl/HIL_Regs_AXI.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/bilinear_solver/src/BilinearSolverUnit.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/bilinear_solver/src/BilinearSolverHandler.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/clarke_transform/src/ClarkeTransform.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/edge_detector/src/EdgeDetector.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/npc_modulator/src/NPCModulator.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/npc_modulator/src/NPCGateDriver.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/npc_modulator/src/NPCManager.vhd
read_vhdl -vhdl2008 $root_dir/src/rtl/TIM_Solver.vhd
read_vhdl -vhdl2008 $root_dir/src/rtl/IIRFilter.vhd
read_vhdl -vhdl2008 $root_dir/src/rtl/HIL_AXI_Top.vhd
check_syntax
puts "SYNTAX_CHECK_OK"
