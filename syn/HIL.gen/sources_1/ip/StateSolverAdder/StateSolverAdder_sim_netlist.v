// Copyright 1986-2021 Xilinx, Inc. All Rights Reserved.
// --------------------------------------------------------------------------------
// Tool Version: Vivado v.2021.2 (win64) Build 3367213 Tue Oct 19 02:48:09 MDT 2021
// Date        : Tue Jun 25 13:14:13 2024
// Host        : BRJGSD317426 running 64-bit major release  (build 9200)
// Command     : write_verilog -force -mode funcsim
//               c:/Users/contardii/Desktop/Hardware-in-the-Loop/syn/HIL.gen/sources_1/ip/StateSolverAdder/StateSolverAdder_sim_netlist.v
// Design      : StateSolverAdder
// Purpose     : This verilog netlist is a functional simulation representation of the design and should not be modified
//               or synthesized. This netlist cannot be used for SDF annotated simulation.
// Device      : xc7s100fgga676-2
// --------------------------------------------------------------------------------
`timescale 1 ps / 1 ps

(* CHECK_LICENSE_TYPE = "StateSolverAdder,c_addsub_v12_0_14,{}" *) (* downgradeipidentifiedwarnings = "yes" *) (* x_core_info = "c_addsub_v12_0_14,Vivado 2021.2" *) 
(* NotValidForBitStream *)
module StateSolverAdder
   (A,
    B,
    CLK,
    S);
  (* x_interface_info = "xilinx.com:signal:data:1.0 a_intf DATA" *) (* x_interface_parameter = "XIL_INTERFACENAME a_intf, LAYERED_METADATA undef" *) input [31:0]A;
  (* x_interface_info = "xilinx.com:signal:data:1.0 b_intf DATA" *) (* x_interface_parameter = "XIL_INTERFACENAME b_intf, LAYERED_METADATA undef" *) input [31:0]B;
  (* x_interface_info = "xilinx.com:signal:clock:1.0 clk_intf CLK" *) (* x_interface_parameter = "XIL_INTERFACENAME clk_intf, ASSOCIATED_BUSIF s_intf:c_out_intf:sinit_intf:sset_intf:bypass_intf:c_in_intf:add_intf:b_intf:a_intf, ASSOCIATED_RESET SCLR, ASSOCIATED_CLKEN CE, FREQ_HZ 100000000, FREQ_TOLERANCE_HZ 0, PHASE 0.0, INSERT_VIP 0" *) input CLK;
  (* x_interface_info = "xilinx.com:signal:data:1.0 s_intf DATA" *) (* x_interface_parameter = "XIL_INTERFACENAME s_intf, LAYERED_METADATA undef" *) output [31:0]S;

  wire [31:0]A;
  wire [31:0]B;
  wire CLK;
  wire [31:0]S;
  wire NLW_U0_C_OUT_UNCONNECTED;

  (* C_ADD_MODE = "0" *) 
  (* C_AINIT_VAL = "0" *) 
  (* C_A_TYPE = "0" *) 
  (* C_A_WIDTH = "32" *) 
  (* C_BORROW_LOW = "1" *) 
  (* C_BYPASS_LOW = "0" *) 
  (* C_B_CONSTANT = "0" *) 
  (* C_B_TYPE = "0" *) 
  (* C_B_VALUE = "00000000000000000000000000000000" *) 
  (* C_B_WIDTH = "32" *) 
  (* C_CE_OVERRIDES_BYPASS = "1" *) 
  (* C_CE_OVERRIDES_SCLR = "0" *) 
  (* C_HAS_BYPASS = "0" *) 
  (* C_HAS_CE = "0" *) 
  (* C_HAS_C_IN = "0" *) 
  (* C_HAS_C_OUT = "0" *) 
  (* C_HAS_SCLR = "0" *) 
  (* C_HAS_SINIT = "0" *) 
  (* C_HAS_SSET = "0" *) 
  (* C_IMPLEMENTATION = "1" *) 
  (* C_LATENCY = "2" *) 
  (* C_OUT_WIDTH = "32" *) 
  (* C_SCLR_OVERRIDES_SSET = "1" *) 
  (* C_SINIT_VAL = "0" *) 
  (* C_VERBOSITY = "0" *) 
  (* C_XDEVICEFAMILY = "spartan7" *) 
  (* downgradeipidentifiedwarnings = "yes" *) 
  (* is_du_within_envelope = "true" *) 
  StateSolverAdder_c_addsub_v12_0_14 U0
       (.A(A),
        .ADD(1'b1),
        .B(B),
        .BYPASS(1'b0),
        .CE(1'b1),
        .CLK(CLK),
        .C_IN(1'b0),
        .C_OUT(NLW_U0_C_OUT_UNCONNECTED),
        .S(S),
        .SCLR(1'b0),
        .SINIT(1'b0),
        .SSET(1'b0));
endmodule
`pragma protect begin_protected
`pragma protect version = 1
`pragma protect encrypt_agent = "XILINX"
`pragma protect encrypt_agent_info = "Xilinx Encryption Tool 2021.2"
`pragma protect key_keyowner="Synopsys", key_keyname="SNPS-VCS-RSA-2", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=128)
`pragma protect key_block
iNiDb0ekPhRUbs/MzEotkv91aS3Hn7NpPOvNwhBA71ib54e/iuFgxDWsHQhG//uPFNOQcsw48NJ/
Jex9v3jJpOAvrsbpE1xtyr06RPHTtBrhLn5oy/JPLRnDikCjDL7pl2nz8/4NFppZ4IOdMQSsgZ6s
7cLy3ssFtw8YHgZpBBI=

`pragma protect key_keyowner="Aldec", key_keyname="ALDEC15_001", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
xMdWfJ9yC+dW7Z4tqvPOuJC1+I94TxwMeGVXcRxTpVQudL778iGxfViPG7+xFYupI1L28MxOHog5
8UcMSrFy49thnK0phUnIHj0aC6gyX5BTyX9O2yqRn+Tb0ViZwaw8RNb32PlwlnlwQ/6N6ZU9Y9aG
YFAdhmgN+2Xk4zUSzRuS4Fkh8aeMb+9XdKOXvagJC/n45GdxH8sqkEUbk/QiV8gGerqj5/G5/GwS
QvuOB3Sq1YSyUp1D7w4IQ4bJiFJESFOi5U2UE7u1h+1gzpJDnRrR1s84sELZRdUDynvMahqLleXZ
IWFY2+0qfSJmtHyzvV5D7u27zKevnVVSjKft+g==

`pragma protect key_keyowner="Mentor Graphics Corporation", key_keyname="MGC-VELOCE-RSA", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=128)
`pragma protect key_block
BXcxoAPS0tOe7iNiaiBkfnEQ6RK9h9ZdYl0ZQZ9gD+ivSxvHRqUQaNUJXADK+j/yHS3kFc9O9bHv
9apdYXON7IMZ9RLTfkh4tIbx4BGrm/PD1bNIEZES7Ggj/xNmgG+KoydQMFTsML7SQ21p7edBUfV2
az9eYYO2SbJM4Vnex/4=

`pragma protect key_keyowner="Mentor Graphics Corporation", key_keyname="MGC-VERIF-SIM-RSA-2", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
PWOAiRdoP7UJP31mBYgem1wyfxKBGPCYYuy7qK1OPyroUHrsrRm0rZWFQbakJzsfCiqiBbes1Pdp
FoS53FX/0oO/nGzrbleR9IKNRGwjSKaUMfAwPhBe3I31YsUwdVUMEm0draA/0Bu0frhCP/0jFhKQ
HicTG99WiRHsLh+F6Xz6QXtxjRhNhWEmp7tK+Z+a7g+N8LWRI2JpIQ272d9VQ61BaLlYfCqHUkHw
ThTl6gfzihr1Ngg2QM5mtIXn8OB6+fq3s9W2CR6TBAvGrx17Z8ej+u3fxiXxC+hBvQjWJ6ri0Top
bA0fhxTpucHxWUd+X+DhmNLTh/f+O3HV2Qpcsw==

`pragma protect key_keyowner="Real Intent", key_keyname="RI-RSA-KEY-1", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
botoKE8YfJkzZ/fegvRBoauY+UFblsqeTMPajI8WL2DBCRzCZJ9Qk/AYzzg+PUnrWUsoMrTJBGyn
gi8WNpzpMX8vvcpKlw8goBzVjdTNmI1s9S0E+VsI1yVv6BIJNCpUF+5EMLdX8/DiJlnuRanoMrvC
KGgBmcKqG7oRhK8xe5pzt7tMew5ocXeCa73sQSLmXuEgUF3UVgaIEpZcsxwiXmE2Av9Y6V+8CSvq
+Kfe/xfivs0EagmHnRhzTM0RvsI3OWHwM7UoosrQd3SFdhg0MFJga+3RHNAK/K7GDL4b3RHD5bQj
9a1gFdowA72kPKeFSBiYlgX6Vk9Uwm2F+V/kSg==

`pragma protect key_keyowner="Xilinx", key_keyname="xilinxt_2021_01", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
lihXgVbpHCLec3zc0ec/06bvVG8syHdsLieKcT9rurQvsbFuEgs53hupuKiQVpUO75Rlflsu9Uv7
M1kUEvj0hLqSwp51FfBdIFyDn69Y/AR9B3nk5K135817Ii5ef0MMxeTSV36GglTaxPcxRJbXKlei
Nh0/cGeo0C8fqlrdb7l2aLKeeo9GaYgnzabE/VAGK3Kvr/UJbmK2eRfLlPygyEE2Hz4VYkVXisIZ
MLfZuqs0KBE7OdqwtqhW0cv/zMjRCl+Ton6KCq1NDbf5iAJGaVns2C8FlvsDnvW98hupBmOnntWx
+cSxLW5CnVkSSDuLYwSmB/VDFDZoKbAAPHcKWg==

`pragma protect key_keyowner="Metrics Technologies Inc.", key_keyname="DSim", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
bslnbMuzuE/h0dU1KUmyBtZ9YobdFoUvmIJOrSIMm1QHKHywokHfs/tstG3kbnleE5Ro3QbFvkee
MAslPB9/9GMe/K/9oy/NUwk7CdOKMDnWe6bjAzHdnN6rqGH8LyHfwibusv1+Ggl/dI+eT7fXvxNf
GalIV+qeXkw58Q8O8q/FoJMuwbuwcSGXWGWU+qSZ44Vj4aHHqMw6AvrJ3nWXG1Aa99MNUc7H9KAC
fL/xXWAYYUs0Aqqfj7hdBSkcTp8RLAb0NH2e/+ve6WJ5Y8lWNAyNlqNz/PW/FvxJwZvYCN5ALqAn
XPV0+dZ+1F6SjA2qB8uYqVSHe2sF4AgOSUb0Yg==

`pragma protect key_keyowner="Atrenta", key_keyname="ATR-SG-RSA-1", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=384)
`pragma protect key_block
KUnwEk0xEpdk2Q3CoTxn9CRe6h/F7eWo/AjrPR0pRlPkFpPN084BeB9Y0fdrjgkq+3HXC4zvjgDR
HGtLYulQ/DDCcVou7MBx+WsobjDsPw4aytnHFJhdPl1/gu90mG3irpFwUndHqHd5KOIno4hRyyVj
ntNaLqfhtx97ZFT7dzeS4sr9hR5umMXx8eagFMAL0SKuooqN5ma5Kn5yRTlFXeVZaOVeeodaDaTe
u+OLoCcbLeOyuraazX0w05ROt1RWuQhiAHJr5D+PdtFH6PTheFQIQp72F4YJVS/Xw+0kGSBAkqw0
FleW7Pxa+YHT/FS6kuvwJ5uAhLIHGM1453HF6YOB/1TCDOa2ntNezXMJIFtsfvAAHyaSJ2XMNrD3
feFFBLqTImohKBoaNkp7O7foRfLi5R/oAlMMzRg83P/99YLyjfIm3xkD3eia2CAK/2qk4ZtC2JQ3
4aJcd5YcoSYGjVfXix9p+pfKHaa/jbY+Vh5Z3dVT8Romtkzvu5jg+UbJ

`pragma protect key_keyowner="Cadence Design Systems.", key_keyname="CDS_RSA_KEY_VER_1", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
P0U2cnGBY9QMyeqr0dOgxj1qNLQ9oatsneQM/zp8ImZGMa9l89mK7lP6/iTxsbrSbC19vRKLXHpw
FTJYNfqvgRZhS7DxQb5OwgYRsbNrhsqUkrU6fD4YcLCVJvUsq4FGf2GMp0SBEmXMlu0H57IA3Ycx
grGxw4dQSY2pM7fKezkaKsACbitFQrg/Q6XzNrg49L/dKrBnQzoDIcgA4wyQrdpLLWdScsi34/UM
96uXBX5B4OAKjIMOlIKwRQov3zD06mx28NQD4VizPa1T5UyqFMRb5eW6zlTHzEI6+x7KVH1IEyUn
4tcbk3Sz3i/RmX3lguEbJEV6kLotF8iEhuyTHw==

`pragma protect key_keyowner="Mentor Graphics Corporation", key_keyname="MGC-PREC-RSA", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
QtUBN/DkEQxjN1PW6XqEHimpzi3s0lI7W2t5emUrWiB/WwtOUzSmyr5Y17yx3GVrFJoyODC1mAKz
u49PpZVYFnciAurre0UklkUJ7ZgLIaPAOuNRMlZpKT/NxQtnvKv7pzxdiK99vc3JvLRygSv9py5Y
B3hhi7xaS8H1zmNfoXBJ6XC2gSGO7IfKNcPdWAqdWTxQ1IRK1gsRYtoYFQxMRu7K3j+w9W40w3Sp
Gxe8AZPgPTfZ9NGDG9ogaTTX6y4uID4oon8LbhJY+HWte7vDd77ZLarGD5UFyzyAMPvvl9bzXHva
NZXGU/vANmXxOa4heUb/ADiVWx7x2bVYgUDwWg==

`pragma protect key_keyowner="Synplicity", key_keyname="SYNP15_1", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
SDVGf7xTTO6E0eRC5d/EVQe+NXBJZCYdXNnDBcT6F7D6xmwLTFhV8ch2CzYu9aGuvW6LDiAyDL+n
pBsFSNIaIi5q/9kw5+BykJ3sKd3FCS87lORH0ChfAmJqj5kvHvxvTjngSqC2lGpoiiKJshgoClxz
K+d3oqE1IfeEvASRe8mAyTjAE8NQcc3b4NBK4zFrMcyqF3i3OX3vmeDed8xJK2u6cG1aSCty8oEk
pHOO+9mdLT7Yyj4AENs5UWFUoW/Hs/JjR/wbKc+u4+bUOPW7B/Oy8nW/SSYeJ1MVr+s7Z5XsS4Ez
jbIMEMcHpmPXzy2Aeug+KhPORvjjY1c+Vx7Ehg==

`pragma protect data_method = "AES128-CBC"
`pragma protect encoding = (enctype = "BASE64", line_length = 76, bytes = 14464)
`pragma protect data_block
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
`pragma protect end_protected
`ifndef GLBL
`define GLBL
`timescale  1 ps / 1 ps

module glbl ();

    parameter ROC_WIDTH = 100000;
    parameter TOC_WIDTH = 0;
    parameter GRES_WIDTH = 10000;
    parameter GRES_START = 10000;

//--------   STARTUP Globals --------------
    wire GSR;
    wire GTS;
    wire GWE;
    wire PRLD;
    wire GRESTORE;
    tri1 p_up_tmp;
    tri (weak1, strong0) PLL_LOCKG = p_up_tmp;

    wire PROGB_GLBL;
    wire CCLKO_GLBL;
    wire FCSBO_GLBL;
    wire [3:0] DO_GLBL;
    wire [3:0] DI_GLBL;
   
    reg GSR_int;
    reg GTS_int;
    reg PRLD_int;
    reg GRESTORE_int;

//--------   JTAG Globals --------------
    wire JTAG_TDO_GLBL;
    wire JTAG_TCK_GLBL;
    wire JTAG_TDI_GLBL;
    wire JTAG_TMS_GLBL;
    wire JTAG_TRST_GLBL;

    reg JTAG_CAPTURE_GLBL;
    reg JTAG_RESET_GLBL;
    reg JTAG_SHIFT_GLBL;
    reg JTAG_UPDATE_GLBL;
    reg JTAG_RUNTEST_GLBL;

    reg JTAG_SEL1_GLBL = 0;
    reg JTAG_SEL2_GLBL = 0 ;
    reg JTAG_SEL3_GLBL = 0;
    reg JTAG_SEL4_GLBL = 0;

    reg JTAG_USER_TDO1_GLBL = 1'bz;
    reg JTAG_USER_TDO2_GLBL = 1'bz;
    reg JTAG_USER_TDO3_GLBL = 1'bz;
    reg JTAG_USER_TDO4_GLBL = 1'bz;

    assign (strong1, weak0) GSR = GSR_int;
    assign (strong1, weak0) GTS = GTS_int;
    assign (weak1, weak0) PRLD = PRLD_int;
    assign (strong1, weak0) GRESTORE = GRESTORE_int;

    initial begin
	GSR_int = 1'b1;
	PRLD_int = 1'b1;
	#(ROC_WIDTH)
	GSR_int = 1'b0;
	PRLD_int = 1'b0;
    end

    initial begin
	GTS_int = 1'b1;
	#(TOC_WIDTH)
	GTS_int = 1'b0;
    end

    initial begin 
	GRESTORE_int = 1'b0;
	#(GRES_START);
	GRESTORE_int = 1'b1;
	#(GRES_WIDTH);
	GRESTORE_int = 1'b0;
    end

endmodule
`endif
