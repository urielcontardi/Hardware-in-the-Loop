#!/usr/bin/env bash
# Renderiza todos os diagramas .d2 para SVG e PNG em img/.
# Uso: ./build.sh            (gera SVG + PNG)
#      ./build.sh svg        (só SVG, sem precisar de chromium)
set -euo pipefail

cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

if ! command -v d2 >/dev/null 2>&1; then
  echo "d2 não encontrado. Instale com: curl -fsSL https://d2lang.com/install.sh | sh -s --"
  exit 1
fi

mkdir -p img
ONLY="${1:-all}"
THEME=0          # 0 = Neutral default (claro). Use 200 p/ dark.

for f in *.d2; do
  base="${f%.d2}"
  echo ">> $f"
  d2 -t "$THEME" -l elk "$f" "img/${base}.svg"
  if [ "$ONLY" != "svg" ]; then
    d2 -t "$THEME" -l elk "$f" "img/${base}.png"
  fi
done

echo "OK -> docs/diagrams/img/"
