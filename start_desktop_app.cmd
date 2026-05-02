@echo off
cd /d D:\https\001
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
set QDRANT_URL=http://127.0.0.1:6333
set NO_PROXY=localhost,127.0.0.1,::1
set no_proxy=localhost,127.0.0.1,::1
C:\Users\cc\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m product_image_search.desktop_app
