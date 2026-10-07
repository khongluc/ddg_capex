@echo off
chcp 65001 > nul
echo =====================================================================
echo    HE THONG QUAN LY VA TINH TOAN NGAN SACH DAU TU CAPEX
echo    CONG TY CO PHAN CO KHI XAY DUNG THUONG MAI DAI DUNG (DDC)
echo =====================================================================
echo.
echo Dang khoi dong WebApp CAPEX...
echo Trinh duyet se tu dong mo tai: http://localhost:8501
echo.
python -m streamlit run app.py --server.port 8501
pause
