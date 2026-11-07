#!/bin/bash
# Set up noise_recorder with isolated Python environment
# No global installs required

set -e

cd "$(dirname "$0")"

echo "Creating virtual environment..."
python3 -m venv .venv

echo "Activating and installing dependencies..."
source .venv/bin/activate
pip install -r requirements.txt

echo ""
echo "Setup complete!"
echo ""
echo "To use the project:"
echo "  source .venv/bin/activate   # Activate virtual environment"
echo "  python3 noise_recorder.py --list-devices"
echo "  caffeinate -i python3 noise_recorder.py --device 2"
echo "  python3 noise_report.py top"
echo ""
echo "To install for everyone (optional, only if needed):"
echo "  pip install -r requirements.txt --user"
