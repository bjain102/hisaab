# Dev mode: Flask API in its own window, Vite (with /api proxy) in this one.
# Open http://localhost:5173 for the new UI, http://127.0.0.1:5000/legacy for the old.
Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$PSScriptRoot'; python app.py"
Push-Location "$PSScriptRoot\frontend"
npm run dev
Pop-Location
