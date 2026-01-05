#!/bin/bash
export comfyui_env=prod
# 混淆js
./script/obfuscate.sh

python3 server.py
