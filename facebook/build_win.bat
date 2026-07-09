@echo off
echo Dang cai dat thu vien can thiet...
pip install -r requirements.txt
pip install pyinstaller playwright

echo Dang dong goi ung dung cho Windows...
pyinstaller --noconsole --name "UCMAS_Poster" --collect-all playwright app.py

echo Da dong goi xong! Ban co the tim thay file chay tai: dist\UCMAS_Poster\UCMAS_Poster.exe
pause
