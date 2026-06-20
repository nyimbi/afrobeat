#!/bin/bash
# Install RVC (Retrieval-based Voice Conversion) from source
# RVC is not on PyPI — must be installed from GitHub
set -euo pipefail
pip install git+https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git@main#egg=rvc \
    fairseq \
    faiss-cpu \
    praat-parselmouth \
    pyworld \
    || echo "WARNING: RVC installation failed — voice synthesis will be disabled"
