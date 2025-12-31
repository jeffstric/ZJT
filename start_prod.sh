#!/bin/bash
export comfyui_env=prod
python3 server.py

# 混淆js
./script/obfuscate.sh
