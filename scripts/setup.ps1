# ============================================
# MendixFormAgent — Setup Script (Windows PowerShell)
# ============================================

$ErrorActionPreference = "Stop"

Write-Host "=== MendixFormAgent Setup ===" -ForegroundColor Cyan

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[1/5] $pythonVersion detectado" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python 3.11+ es requerido. Instálalo desde https://python.org" -ForegroundColor Red
    exit 1
}

# Check Node.js
try {
    $nodeVersion = node --version 2>&1
    Write-Host "[2/5] Node.js $nodeVersion detectado" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Node.js 18+ es requerido. Instálalo desde https://nodejs.org" -ForegroundColor Red
    exit 1
}

# Install Python dependencies
Write-Host "[3/5] Instalando dependencias Python..." -ForegroundColor Yellow
pip install -e ".[dev]"

# Install Node.js dependencies
Write-Host "[4/5] Instalando dependencias Node.js..." -ForegroundColor Yellow
Push-Location mendix_sdk
npm install
Pop-Location

# Build TypeScript
Write-Host "[5/5] Compilando módulo TypeScript..." -ForegroundColor Yellow
Push-Location mendix_sdk
npm run build
Pop-Location

# Check .env
if (-not (Test-Path ".env")) {
    Write-Host ""
    Write-Host "AVISO: No se encontró archivo .env" -ForegroundColor Yellow
    Write-Host "Copia .env.example como .env y completa los valores:"
    Write-Host "  Copy-Item .env.example .env"
}

Write-Host ""
Write-Host "=== Setup completo ===" -ForegroundColor Cyan
Write-Host "Prueba con: python -m mendex --help"
