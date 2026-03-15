"""Reference induction-motor model backend for cocotb comparisons.

Primary backend compiles and loads the C model from the git submodule.
If a native C toolchain is unavailable, it falls back to a Python B2-equation model.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


MODEL_A = 0
MODEL_B = 1
MODEL_B2 = 2
MODEL_C = 3
MODEL_D = 4


@dataclass(frozen=True)
class IMPhysicalParams:
    """Motor and simulation parameters matching TIM_Solver defaults."""

    rs: float
    rr: float
    lm: float
    ls: float
    lr: float
    j: float
    npp: float
    ts: float

    @classmethod
    def defaults(cls) -> "IMPhysicalParams":
        return cls(
            rs=0.435,
            rr=0.2826,
            lm=109.9442e-3,
            ls=3.1364e-3,
            lr=6.3264e-3,
            j=0.192,
            npp=2.0,
            ts=100.0e-9,
        )


@dataclass(frozen=True)
class IMState:
    i_alpha: float
    i_beta: float
    flux_alpha: float
    flux_beta: float
    speed_mech: float


class _CIMParams(ctypes.Structure):
    _fields_ = [
        ("Rs", ctypes.c_double),
        ("Rr", ctypes.c_double),
        ("Lm", ctypes.c_double),
        ("Ls", ctypes.c_double),
        ("Lr", ctypes.c_double),
        ("J", ctypes.c_double),
        ("npp", ctypes.c_double),
        ("Ts", ctypes.c_double),
    ]


class _CIMInputs(ctypes.Structure):
    _fields_ = [
        ("Va", ctypes.c_double),
        ("Vb", ctypes.c_double),
        ("Vc", ctypes.c_double),
        ("Tload", ctypes.c_double),
    ]


class _CIMOutputs(ctypes.Structure):
    _fields_ = [
        ("ia", ctypes.c_double),
        ("ib", ctypes.c_double),
        ("ic", ctypes.c_double),
        ("wr", ctypes.c_double),
        ("wmec", ctypes.c_double),
        ("Te", ctypes.c_double),
    ]


class _CIMModel(ctypes.Structure):
    _fields_ = [
        ("params", _CIMParams),
        ("type", ctypes.c_int),
        ("inp", _CIMInputs),
        ("out", _CIMOutputs),
        ("priv", ctypes.c_void_p),
    ]


class _CIMInternalInputs(ctypes.Structure):
    _fields_ = [
        ("valpha", ctypes.c_double),
        ("vbeta", ctypes.c_double),
        ("v0", ctypes.c_double),
    ]


class _CIMStates(ctypes.Structure):
    _fields_ = [
        ("is_alpha", ctypes.c_double),
        ("is_beta", ctypes.c_double),
        ("ir_alpha", ctypes.c_double),
        ("ir_beta", ctypes.c_double),
        ("fluxR_alpha", ctypes.c_double),
        ("fluxR_beta", ctypes.c_double),
        ("wr", ctypes.c_double),
        ("wm", ctypes.c_double),
        ("Te", ctypes.c_double),
        ("isd", ctypes.c_double),
        ("isq", ctypes.c_double),
        ("fluxRd", ctypes.c_double),
        ("angleR", ctypes.c_double),
    ]


class _CIMPrivateData(ctypes.Structure):
    _fields_ = [
        ("inp", _CIMInternalInputs),
        ("out", _CIMStates),
    ]


class _CReferenceBackend:
    def __init__(self, params: IMPhysicalParams, model_type: int) -> None:
        project_root = Path(__file__).resolve().parents[3]
        src_dir = project_root / "verification" / "reference_models" / "induction-motor-model" / "src"
        c_src = src_dir / "IM_Model.c"
        if not c_src.exists():
            raise FileNotFoundError(f"Reference C source not found: {c_src}")

        build_dir = project_root / "verification" / "cocotb" / "sim_build" / "reference_model"
        build_dir.mkdir(parents=True, exist_ok=True)
        lib_path = build_dir / "libim_model.so"

        if (not lib_path.exists()) or (c_src.stat().st_mtime > lib_path.stat().st_mtime):
            compiler = os.environ.get("CC", "gcc")
            cmd = [
                compiler,
                "-O2",
                "-fPIC",
                "-shared",
                "-I",
                str(src_dir),
                str(c_src),
                "-o",
                str(lib_path),
                "-lm",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                stderr = proc.stderr.strip()
                stdout = proc.stdout.strip()
                raise RuntimeError(
                    f"Failed to compile C reference model (rc={proc.returncode}).\n"
                    f"stdout:\n{stdout}\n"
                    f"stderr:\n{stderr}"
                )

        self._lib = ctypes.CDLL(str(lib_path))
        self._model = _CIMModel()

        self._lib.IM_Init.argtypes = [ctypes.POINTER(_CIMModel)]
        self._lib.IM_SetParams.argtypes = [ctypes.POINTER(_CIMModel), ctypes.POINTER(_CIMParams)]
        self._lib.IM_SetInputs.argtypes = [ctypes.POINTER(_CIMModel), ctypes.POINTER(_CIMInputs)]
        self._lib.IM_TypeModel.argtypes = [ctypes.POINTER(_CIMModel), ctypes.c_int]
        self._lib.IM_SimulateStep.argtypes = [ctypes.POINTER(_CIMModel)]

        self._lib.IM_Init(ctypes.byref(self._model))
        c_params = _CIMParams(
            params.rs,
            params.rr,
            params.lm,
            params.ls,
            params.lr,
            params.j,
            params.npp,
            params.ts,
        )
        self._lib.IM_SetParams(ctypes.byref(self._model), ctypes.byref(c_params))
        self._lib.IM_TypeModel(ctypes.byref(self._model), ctypes.c_int(model_type))

    def step(self, va: float, vb: float, vc: float, tload: float) -> IMState:
        c_inputs = _CIMInputs(va, vb, vc, tload)
        self._lib.IM_SetInputs(ctypes.byref(self._model), ctypes.byref(c_inputs))
        self._lib.IM_SimulateStep(ctypes.byref(self._model))

        priv_ptr = ctypes.cast(self._model.priv, ctypes.POINTER(_CIMPrivateData))
        if not priv_ptr:
            raise RuntimeError("C model private data pointer is null")

        st = priv_ptr.contents.out
        return IMState(
            i_alpha=st.is_alpha,
            i_beta=st.is_beta,
            flux_alpha=st.fluxR_alpha,
            flux_beta=st.fluxR_beta,
            speed_mech=st.wm,
        )


class _PythonB2Backend:
    def __init__(self, params: IMPhysicalParams) -> None:
        self._p = params
        self.is_alpha = 0.0
        self.is_beta = 0.0
        self.flux_alpha = 0.0
        self.flux_beta = 0.0
        self.wm = 0.0

    def step(self, va: float, vb: float, vc: float, tload: float) -> IMState:
        valpha = (2.0 / 3.0) * (va - 0.5 * vb - 0.5 * vc)
        vbeta = (1.0 / (3.0**0.5)) * (vb - vc)

        rs = self._p.rs
        rr = self._p.rr
        lm = self._p.lm
        ls_total = self._p.ls + self._p.lm
        lr_total = self._p.lr + self._p.lm
        j = self._p.j
        npp = self._p.npp
        ts = self._p.ts

        k = 1.0 / (lr_total * (lm * lm - lr_total * ls_total))

        dis_alpha = k * (
            lm * lm * rr * self.is_alpha
            - lm * lr_total * npp * self.wm * self.flux_beta
            - lm * rr * self.flux_alpha
            + lr_total * lr_total * rs * self.is_alpha
            - lr_total * lr_total * valpha
        )
        dis_beta = k * (
            lm * lm * rr * self.is_beta
            + lm * lr_total * npp * self.wm * self.flux_alpha
            - lm * rr * self.flux_beta
            + lr_total * lr_total * rs * self.is_beta
            - lr_total * lr_total * vbeta
        )
        dflux_alpha = (
            lm * rr * self.is_alpha
            - lr_total * npp * self.wm * self.flux_beta
            - rr * self.flux_alpha
        ) / lr_total
        dflux_beta = (
            lm * rr * self.is_beta
            + lr_total * npp * self.wm * self.flux_alpha
            - rr * self.flux_beta
        ) / lr_total

        te = (3.0 / 2.0) * (npp * lm / lr_total) * (
            self.flux_alpha * self.is_beta - self.flux_beta * self.is_alpha
        )
        dwm = (te - tload) / j

        self.is_alpha += dis_alpha * ts
        self.is_beta += dis_beta * ts
        self.flux_alpha += dflux_alpha * ts
        self.flux_beta += dflux_beta * ts
        self.wm += dwm * ts

        return IMState(
            i_alpha=self.is_alpha,
            i_beta=self.is_beta,
            flux_alpha=self.flux_alpha,
            flux_beta=self.flux_beta,
            speed_mech=self.wm,
        )


class InductionMotorReferenceModel:
    """Reference motor model with automatic C/Python backend selection."""

    def __init__(
        self,
        params: IMPhysicalParams | None = None,
        model_type: int = MODEL_B2,
        backend: str = "auto",
    ) -> None:
        self.params = params if params is not None else IMPhysicalParams.defaults()
        self.backend_name = ""

        backend_error = None
        if backend in ("auto", "c"):
            try:
                self._impl = _CReferenceBackend(self.params, model_type)
                self.backend_name = "c"
                return
            except Exception as exc:  # pragma: no cover - fallback path
                backend_error = exc
                if backend == "c":
                    raise

        self._impl = _PythonB2Backend(self.params)
        self.backend_name = "python-b2"

        if backend_error is not None:
            # Keep useful context available to callers for logging.
            self.fallback_reason = str(backend_error)
        else:
            self.fallback_reason = ""

    def step(self, va: float, vb: float, vc: float, tload: float) -> IMState:
        return self._impl.step(va, vb, vc, tload)
