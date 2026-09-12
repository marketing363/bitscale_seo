#!/bin/bash
# Double-click this file (Mac) to launch the Brand Brain UI in your browser.
# First run: it installs requirements. It opens http://localhost:8501
cd "$(dirname "$0")" || exit 1
echo "▶ Starting Brand Brain UI…"
command -v streamlit >/dev/null 2>&1 || pip install -r requirements.txt
exec streamlit run ui/app.py
