# MACSWC Engine Runner - API Mode without GUI (Short Display)
# This script sets up the configuration and runs the simulation

Write-Host ""
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " MACSWC - API Mode (Short Display, No GUI)" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

# Copy the appropriate .env configuration
Copy-Item -Path ".env.api_short" -Destination ".env" -Force
Write-Host "[OK] Configuration loaded: API + Short Display (No GUI)" -ForegroundColor Green
Write-Host ""

# Run the simulation
Write-Host "Starting simulation..." -ForegroundColor Yellow
Write-Host ""
C:/Users/Duki/miniconda3/envs/waragent/python.exe -m WorldEngine.playground
