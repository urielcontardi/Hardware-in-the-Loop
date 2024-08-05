// Copyright 1986-2021 Xilinx, Inc. All Rights Reserved.
// --------------------------------------------------------------------------------
// Tool Version: Vivado v.2021.2 (win64) Build 3367213 Tue Oct 19 02:48:09 MDT 2021
// Date        : Tue Jun 25 13:14:13 2024
// Host        : BRJGSD317426 running 64-bit major release  (build 9200)
// Command     : write_verilog -force -mode synth_stub
//               c:/Users/contardii/Desktop/Hardware-in-the-Loop/syn/HIL.gen/sources_1/ip/StateSolverAdder/StateSolverAdder_stub.v
// Design      : StateSolverAdder
// Purpose     : Stub declaration of top-level module interface
// Device      : xc7s100fgga676-2
// --------------------------------------------------------------------------------

// This empty module with port declaration file causes synthesis tools to infer a black box for IP.
// The synthesis directives are for Synopsys Synplify support to prevent IO buffer insertion.
// Please paste the declaration into a Verilog source file or add the file as an additional source.
(* x_core_info = "c_addsub_v12_0_14,Vivado 2021.2" *)
module StateSolverAdder(A, B, CLK, S)
/* synthesis syn_black_box black_box_pad_pin="A[31:0],B[31:0],CLK,S[31:0]" */;
  input [31:0]A;
  input [31:0]B;
  input CLK;
  output [31:0]S;
endmodule
