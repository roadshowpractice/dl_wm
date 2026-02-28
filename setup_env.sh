#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "[1/3] conda env update..."
conda env update -f environment.yml --prune

# allow conda activate in scripts
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate dl_wm

echo "[2/3] pin setuptools so pkg_resources exists..."
python -m pip uninstall -y setuptools >/dev/null 2>&1 || true
python -m pip install "setuptools==68.2.2"

python -c "import pkg_resources; print('pkg_resources OK')"

echo "[3/3] install whisper..."
WHISPER_VERSION="${WHISPER_VERSION:-20230314}"
python -m pip install --no-build-isolation "openai-whisper==${WHISPER_VERSION}"

python -c "import whisper; print('whisper OK')"
