#!/usr/bin/env python3
"""prime_c_model.py — compila o modelo C de referencia uma unica vez, antes
de qualquer worker paralelo comecar.

models/im_reference_model.py compila verification/cocotb/sim_build/reference_model/libim_model.so
sob demanda, na primeira vez que InductionMotorReferenceModel(backend="c")
roda, e so recompila se o .so estiver ausente ou mais antigo que IM_Model.c.
Se duas execucoes cocotb paralelas caem nesse caminho de compilacao ao mesmo
tempo, os dois gcc escrevem no mesmo arquivo de saida e um processo pode
tentar dlopen um .so parcialmente escrito pelo outro. Chamar esta funcao uma
vez, serialmente, antes de abrir o pool paralelo garante que o .so ja existe
e esta atualizado antes de qualquer worker toca-lo.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.im_reference_model import InductionMotorReferenceModel


def ensure_c_model_built() -> Path:
    model = InductionMotorReferenceModel(backend="c")
    if model.backend_name != "c":
        raise RuntimeError(
            f"esperava backend C, veio {model.backend_name!r} — "
            "verifique se o gcc esta instalado e se IM_Model.c compila"
        )
    so_path = (
        Path(__file__).resolve().parent.parent
        / "sim_build" / "reference_model" / "libim_model.so"
    )
    if not so_path.exists():
        raise RuntimeError(f"esperava {so_path} existir apos o priming")
    return so_path


if __name__ == "__main__":
    path = ensure_c_model_built()
    print(f"libim_model.so pronto: {path}")
