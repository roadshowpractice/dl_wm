#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "[1/4] conda env update..."
conda env update -f environment.yml --prune

# allow conda activate in scripts
source "$(conda info --base)/etc/profile.d/conda.sh"

# workaround for MKL activation script + strict nounset
export MKL_INTERFACE_LAYER=""

conda activate dl_wm

echo "[2/4] pin setuptools so pkg_resources exists..."
python -m pip uninstall -y setuptools >/dev/null 2>&1 || true
python -m pip install "setuptools==68.2.2"

python -c "import pkg_resources; print('pkg_resources OK')"

echo "[3/4] install whisper..."
WHISPER_VERSION="${WHISPER_VERSION:-20230314}"
python -m pip install --no-build-isolation "openai-whisper==${WHISPER_VERSION}"

python -c "import whisper; print('whisper OK')"

echo "[4/4] install faster-whisper (alternate transcription engine, see docs/transcription_engines.md)..."
FASTER_WHISPER_VERSION="${FASTER_WHISPER_VERSION:-1.2.1}"
python -m pip install "faster-whisper==${FASTER_WHISPER_VERSION}"

python -c "import faster_whisper; print('faster_whisper OK')"

# add activation alias
if ! grep -q "alias cad=" ~/.bashrc; then
    echo "alias cad='conda activate dl_wm'" >> ~/.bashrc
    echo "Added alias 'cad' to ~/.bashrc"
fi

echo
echo "Setup complete."
echo "Run this once:"
echo "    source ~/.bashrc"
echo "Then activate with:"
echo "    cad"
