#!/bin/bash
# DreamWeaver Backend - Quick Start Script
# =========================================

set -e

echo "🌙 DreamWeaver Backend Setup"
echo "============================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not found."
    exit 1
fi

echo "Python: $(python3 --version)"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate
echo "Virtual env: activated"

# Install minimal dependencies
echo ""
echo "Installing dependencies..."
pip install -q fastapi uvicorn[standard] pydantic python-dotenv httpx

# Install optional dependencies (non-fatal if they fail)
echo ""
echo "Installing optional packages (Groq, audio processing)..."
pip install -q groq 2>/dev/null || echo "  Warning: groq package not installed (AI generation will use mock data)"
pip install -q Pillow cairosvg 2>/dev/null || echo "  Warning: image packages not installed (album art will be skipped)"
pip install -q pydub 2>/dev/null || echo "  Warning: pydub not installed (audio mixing will be skipped)"

# Check for .env
if [ ! -f ".env" ]; then
    echo ""
    echo "Warning: .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "Please edit .env with your API keys."
fi

# Generate seed data
echo ""
echo "Generating seed data..."
python3 scripts/seed_data.py

# Start the server
echo ""
echo "============================"
echo "Starting DreamWeaver API..."
echo "============================"
echo ""
echo "  API:     http://localhost:8000"
echo "  Docs:    http://localhost:8000/docs"
echo "  Health:  http://localhost:8000/health"
echo ""
echo "  Mode:    LOCAL DEV (no Firebase required)"
echo "  Data:    In-memory with seed data"
echo ""

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
