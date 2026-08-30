#!/bin/bash

# Este script arranca ambos servidores (Vite y Uvicorn) al mismo tiempo.
trap "trap - SIGTERM && kill -- -$$" SIGINT SIGTERM EXIT

echo "======================================"
echo "    INICIANDO SPX TRADING DECK"
echo "======================================"

cd "$(dirname "$0")"

echo "1. Levantando el Backend (FastAPI)..."
source venv_new/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8000 &

echo "2. Levantando el Frontend (React)..."
cd frontend
npm run dev -- --open --host &

echo "======================================"
echo "   ¡ENTORNO DE TRADING ACTIVADO!"
echo "   La web se abrirá enseguida."
echo "   NO CIERRES ESTA VENTANA NEGRA."
echo "======================================"

wait
