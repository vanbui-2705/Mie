#!/bin/bash

echo "Đang cài đặt thư viện cần thiết..."
pip3 install -r requirements.txt
pip3 install pyinstaller playwright

echo "Đang đóng gói ứng dụng cho Mac..."
pyinstaller --noconsole --name "UCMAS_Poster" --windowed --collect-all playwright app.py

echo "Đã đóng gói xong! Bạn có thể tìm thấy file ứng dụng tại: dist/UCMAS_Poster.app"
