"""Fact-check heurístico de números citados no Capítulo 4 da dissertação
contra os JSONs de métricas do pipeline HIL. Descartável: uso único para
a auditoria de 2026-07-25, não faz parte do pipeline permanente.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[3]
TEX_PATH = REPO_ROOT.parent / "Mestrado_latex/Mestrado/chapters/4-Resultados.tex"

# Números em pt-BR: "0{,}166", "21{,}6", com expoente opcional tipo
# "6{,}1\times10^{-4}".
NUMBER_RE = re.compile(r"(-?\d+)\{,\}(\d+)(?:\\times10\^\{(-?\d+)\})?")
UNIT_HINT_RE = re.compile(r"\\%|rad/s|Wb|\^\\circ|\\circ|A\b|LUT|DSP|BRAM|ns")


@dataclass
class NumberClaim:
    value: float
    unit: str
    context: str
    line: int


@dataclass
class MatchResult:
    claim: NumberClaim
    best_match: float | None
    source_key: str | None
    status: Literal["match", "diverge", "not_found"]


def _parse_value(int_part: str, frac_part: str, exp: str | None) -> float:
    value = float(f"{int_part}.{frac_part}")
    if exp is not None:
        value *= 10 ** int(exp)
    return value


def extract_numbers(tex_path: Path) -> list[NumberClaim]:
    claims: list[NumberClaim] = []
    lines = tex_path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, start=1):
        if line.strip().startswith("%"):
            continue
        for m in NUMBER_RE.finditer(line):
            value = _parse_value(m.group(1), m.group(2), m.group(3))
            tail = line[m.end(): m.end() + 25]
            unit_m = UNIT_HINT_RE.search(tail)
            unit = unit_m.group(0) if unit_m else ""
            start = max(0, m.start() - 40)
            end = min(len(line), m.end() + 40)
            claims.append(
                NumberClaim(value=value, unit=unit, context=line[start:end], line=lineno)
            )
    return claims


def _flatten_sources(sources: dict, prefix: str = "") -> dict[str, float]:
    flat: dict[str, float] = {}
    for key, val in sources.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            flat.update(_flatten_sources(val, path))
        elif isinstance(val, (int, float)):
            flat[path] = float(val)
    return flat


def match_claims(claims: list[NumberClaim], sources: dict) -> list[MatchResult]:
    flat = _flatten_sources(sources)
    results: list[MatchResult] = []
    for claim in claims:
        best_key, best_rel = None, float("inf")
        for key, val in flat.items():
            for candidate in (val, val * 100):
                if candidate == 0 and claim.value == 0:
                    rel = 0.0
                else:
                    diff = abs(candidate - claim.value)
                    rel = diff / max(abs(claim.value), abs(candidate), 1e-12)
                if rel < best_rel:
                    best_rel, best_key = rel, key
        if best_key is None:
            results.append(MatchResult(claim, None, None, "not_found"))
        elif best_rel < 0.01:
            results.append(MatchResult(claim, flat[best_key], best_key, "match"))
        elif best_rel < 0.15:
            results.append(MatchResult(claim, flat[best_key], best_key, "diverge"))
        else:
            results.append(MatchResult(claim, None, None, "not_found"))
    return results


def load_sources() -> dict:
    base = REPO_ROOT / "docs/results-chapter/figures"
    sources: dict = {}
    for level in ("l2", "l3", "l4"):
        path = base / level / f"{level}_metrics.json"
        if path.is_file():
            sources[level] = json.loads(path.read_text())
    return sources


def main() -> None:
    claims = extract_numbers(TEX_PATH)
    sources = load_sources()
    results = match_claims(claims, sources)
    out_path = REPO_ROOT / "docs/results-chapter/factcheck_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = [
        {
            "line": r.claim.line,
            "value": r.claim.value,
            "unit": r.claim.unit,
            "context": r.claim.context,
            "status": r.status,
            "source_key": r.source_key,
            "best_match": r.best_match,
        }
        for r in results
    ]
    out_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False))
    n_match = sum(1 for r in results if r.status == "match")
    n_diverge = sum(1 for r in results if r.status == "diverge")
    n_not_found = sum(1 for r in results if r.status == "not_found")
    print(f"match={n_match} diverge={n_diverge} not_found={n_not_found} total={len(results)}")
    for r in results:
        if r.status != "match":
            print(f"  L{r.claim.line} [{r.status}] {r.claim.value} :: {r.claim.context.strip()}")


if __name__ == "__main__":
    main()
