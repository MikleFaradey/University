@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
python fetch_datasets.py
python -m streamlit run app.py
pause
