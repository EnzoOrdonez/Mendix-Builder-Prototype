#!/usr/bin/env bash
# ============================================
# MendixFormAgent — Setup Script (Linux/macOS/Git Bash)
# ============================================
set -euo pipefail

echo "=== MendixFormAgent Setup ==="

# Check Python
if ! command -v python &> /dev/null; then
    echo "ERROR: Python 3.11+ es requerido. Instálalo desde https://python.org"
    exit 1
fi

PYTHON_VERSION=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "[1/5] Python $PYTHON_VERSION detectado"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js 18+ es requerido. Instálalo desde https://nodejs.org"
    exit 1
fi

NODE_VERSION=$(node --version)
echo "[2/5] Node.js $NODE_VERSION detectado"

# Install Python dependencies
echo "[3/5] Instalando dependencias Python..."
pip install -e ".[dev]"

# Install Node.js dependencies
echo "[4/5] Instalando dependencias Node.js..."
cd mendix_sdk && npm install && cd ..

# Build TypeScript
echo "[5/5] Compilando módulo TypeScript..."
cd mendix_sdk && npm run build && cd ..

# Check .env
if [ ! -f .env ]; then
    echo ""
    echo "AVISO: No se encontró archivo .env"
    echo "Copia .env.example como .env y completa los valores:"
    echo "  cp .env.example .env"
fi

echo ""
echo "=== Setup completo ==="
echo "Prueba con: python -m mendex --help"
