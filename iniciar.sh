#!/usr/bin/env sh
# Inicia Neji POS en Linux o macOS. Usa "./iniciar.sh --red" para multicaja.
cd "$(dirname "$0")" || exit 1
if [ ! -f .venv/instalado.txt ]; then
  echo "Preparando Neji POS por primera vez..."
  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt && echo ok > .venv/instalado.txt || exit 1
fi
exec .venv/bin/python run.py "$@"
