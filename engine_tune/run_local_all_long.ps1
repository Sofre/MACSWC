# MACSWC Engine Runner - Local All Agents (Long Display)
# This script sets up the configuration and runs the simulation
# NOTE: Requires Ollama running locally

Write-Host ""
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " MACSWC - Local All Agents (Long Display)" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[WARNING] This mode uses LOCAL Ollama for Country, Secretary, and Board agents" -ForegroundColor Yellow
Write-Host "          Make sure Ollama is running before proceeding!" -ForegroundColor Yellow
Write-Host ""

# Copy the appropriate .env configuration
Copy-Item -Path ".env.local_all_long" -Destination ".env" -Force
Write-Host "[OK] Configuration loaded: Local All Agents + Long Display" -ForegroundColor Green
Write-Host ""

# Run the simulation
Write-Host "Starting simulation..." -ForegroundColor Yellow
Write-Host ""
C:/Users/Duki/miniconda3/envs/waragent/python.exe -m WorldEngine.playground
