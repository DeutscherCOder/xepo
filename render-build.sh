#!/usr/bin/env bash
# Update Paket-Liste und installiere FFmpeg
apt-get update && apt-get install -y ffmpeg

# Installiere Python Pakete
pip install -r requirements.txt
