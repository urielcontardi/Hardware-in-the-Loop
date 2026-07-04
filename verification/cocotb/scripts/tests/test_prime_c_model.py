"""Unit test for prime_c_model.py — verifica que o .so compila e que a
segunda chamada e idempotente (nao recompila se o .c nao mudou)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import prime_c_model


def test_ensure_c_model_built_creates_so():
    so_path = prime_c_model.ensure_c_model_built()
    assert so_path.exists()
    assert so_path.name == "libim_model.so"


def test_ensure_c_model_built_is_idempotent():
    so_path_1 = prime_c_model.ensure_c_model_built()
    mtime_1 = so_path_1.stat().st_mtime
    so_path_2 = prime_c_model.ensure_c_model_built()
    mtime_2 = so_path_2.stat().st_mtime
    assert mtime_1 == mtime_2, "segunda chamada nao deve recompilar um .so inalterado"
