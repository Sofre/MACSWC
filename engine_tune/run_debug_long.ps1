# MACSWC Engine Runner - Debug Mode (Long Display)
# This script sets up the configuration and runs the simulation

Write-Host ""
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " MACSWC - Debug Mode (Long Display)" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

# Copy the appropriate .env configuration
Copy-Item -Path ".env.debug_long" -Destination ".env" -Force
Write-Host "[OK] Configuration loaded: Debug Mode + Long Display" -ForegroundColor Green
Write-Host "[WARNING] Verbose logging enabled" -ForegroundColor Yellow
Write-Host ""

# Run the simulation
Write-Host "Starting simulation..." -ForegroundColor Yellow
Write-Host ""
C:/Users/Duki/miniconda3/envs/waragent/python.exe -m WorldEngine.playground
