clc
clear all

%######################## Inverter #########################
%% LC Filter parameters
n_books     =   1;                   % number of books in parallell
Vdc         =   1500;                % DC Link voltage

L1_book	    =	110e-6;              % filter inductance
R1_book	    =   1.0e-6;              % filter losses
Cf_boook	=	50e-6*3;             % capacitor filter multiplied by 3 due to Delta connection
Cd_book     =   25e-6*3;             % damping capacitor multiplied by 3 due to Delta connection
Ld_book     =   850e-6/3;            % damping inductor divided by 3 due to Delta connection
Rd_book     =   2.5/3;               % damping resistor divided by 3 due to Delta connection

L1	        =	L1_book/n_books;     % filter inductance
R1	        =   R1_book/n_books;     % filter losses
Cf	        =	Cf_boook*n_books;    % capacitor 
Cd          =   Cd_book*n_books;     % damping capacitor 
Ld          =   Ld_book/n_books;     % damping inductor 
Rd          =   Rd_book/n_books;     % damping resistor 

%######################## Grid #########################
f_grid = 60; % 60Hz 
Vgprim_ll = 34.5e3; % 34500 Vrms line to line primary
Vgsec_ll = 925; % 925 Vrms line to line secondary
Vpgsec_ln = 925/sqrt(3)*sqrt(2); % 756 Vpk line secondary
S_trafo = 4.42e6; % Power 4.42MVA
P_loss = 50400; % Power loss from datasheet
Z_trafo = 7.3/100; % 7.3% impedance from datasheet 

% Trafo
Igrid_nom = S_trafo/sqrt(3)/Vgsec_ll;
Zbase = (Vgsec_ll^2)/S_trafo;
N_trafo = Vgprim_ll/Vgsec_ll;

Zeq = Z_trafo * Zbase; 
Req = P_loss / (Igrid_nom^2);
Xeq = sqrt((Zeq^2)-(Req^2));

L_trafo = Xeq / (2 * pi * f_grid); % transformer equivalent inductance
R_trafo = Req; % transformer losses

% Grid Parameters
SCR = 10;
Ssc = SCR * S_trafo;
L_grid = Vgsec_ll^2 / (Ssc * 2 * pi * f_grid);

% L2, R2 
L2 = L_grid + L_trafo;
R2 = R_trafo;

%######################## State Space #########################
A = [
    -R1/L1, 0, 0, -1/L1, 0;
    0, 0, 0, 1/Ld, -1/Ld;
    0, 0, -R2/L2, 1/L2, 0;
    1/Cf, -1/Cf, -1/Cf, -1/(Cf*Rd), 1/(Cf*Rd);
    0, 1/Cd, 0, 1/(Cd*Rd), -1/(Cd*Rd)
];

B = [
    1/L1, 0;
    0, 0;
    0, -1/L2;
    0, 0;
    0, 0
];

C = eye(5);
D = zeros(5, 2);

% Create state-space system
sys_cont = ss(A, B, C, D);

%######################## DsicreteState Space #########################

% Calc Step
%Ts = 500e-9;
Ts 	=  0.000333;
sys_dis = c2d(sys_cont, Ts, 'tustin');

% Get Matrix
Adis = sys_dis.A;
Bdis = sys_dis.B;
Cdis = sys_dis.C;
Ddis = sys_dis.D;

