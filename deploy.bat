@echo off
set PYTHONUTF8=1

echo Building image in ACR (no-wait)...
for /f "tokens=*" %%i in ('az acr build --registry mjhughestickets --image bids-processor:latest --platform linux/amd64 --no-wait . --query "runId" -o tsv 2^>^&1 ^| findstr /v WARNING') do set RUN_ID=%%i
echo Build queued: %RUN_ID%

echo Waiting for build to complete...
:wait
timeout /t 10 /nobreak >nul
for /f "tokens=*" %%s in ('az acr task show-run --registry mjhughestickets --run-id %RUN_ID% --query status -o tsv 2^>nul') do set STATUS=%%s
echo Status: %STATUS%
if "%STATUS%"=="Queued" goto wait
if "%STATUS%"=="Running" goto wait
if not "%STATUS%"=="Succeeded" (
    echo Build failed with status: %STATUS%
    exit /b 1
)

echo Build succeeded. Starting job...
az containerapp job start --name mjhughes-bids-job --resource-group ticket-processor-rg
