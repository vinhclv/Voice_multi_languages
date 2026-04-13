@echo off
title Auto Video Generator - SAFE MODE
cd /d "%~dp0"

echo =====================================================
echo    BUOC 1: KIEM TRA MOI TRUONG
echo =====================================================

:: 1. Kiem tra Python
python --version >nul 2>&1
if %errorlevel% neq 0 goto ERROR_NO_PYTHON

:: 2. Xoa venv cu neu bi loi (De cai lai cho sach)
if exist "venv" (
    :: Kiem tra neu thieu file activate thi xoa luon venv de tao lai
    if not exist "venv\Scripts\activate" (
        echo [INFO] Phat hien venv bi loi. Dang xoa de tao lai...
        rmdir /s /q "venv"
    )
)

if exist "venv" goto VENV_EXIST

:CREATE_VENV
echo [INFO] Folder venv chua co. Dang tao moi...
python -m venv venv
if %errorlevel% neq 0 goto ERROR_VENV_CREATE
goto ACTIVATE

:VENV_EXIST
echo [INFO] Da tim thay venv.

:ACTIVATE
:: 3. Kich hoat moi truong
echo [INFO] Dang kich hoat venv...
call venv\Scripts\activate

:: 4. Nang cap Pip & Cai dat thu vien
echo [INFO] Dang nang cap Pip...
python -m pip install --upgrade pip

if not exist "requirements.txt" goto RUN_TOOL
echo [INFO] Dang cai dat thu vien (BO QUA CACHE)...

:: --- FIX LOI PERMISSION DENIED O DAY ---
:: Them --no-cache-dir de tranh loi Access Denied trong AppData
pip install --no-cache-dir -r requirements.txt --user
:: Neu lenh tren that bai thu lai khong co --user
if %errorlevel% neq 0 (
    echo [INFO] Thu cai dat lai che do Admin...
    pip install --no-cache-dir -r requirements.txt
)

if %errorlevel% neq 0 goto ERROR_INSTALL

:RUN_TOOL
echo.
echo =====================================================
echo    BUOC 2: KHOI CHAY TOOL
echo =====================================================
echo.
python main.py

echo.
echo [INFO] Chuong trinh da ket thuc.
cmd /k
exit

:: =====================================================
:: KHU VUC BAO LOI
:: =====================================================

:ERROR_NO_PYTHON
color 4
echo.
echo [LOI] Khong tim thay Python!
cmd /k
exit

:ERROR_VENV_CREATE
color 4
echo.
echo [LOI] Khong the tao folder 'venv'. 
cmd /k
exit

:ERROR_INSTALL
color 4
echo.
echo [LOI] Cai dat thu vien that bai.
echo Hay thu: Chuot phai vao file .bat -> Run as Administrator
cmd /k
exit