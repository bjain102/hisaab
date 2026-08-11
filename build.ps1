Push-Location "$PSScriptRoot\frontend"
npm run build
$code = $LASTEXITCODE
Pop-Location
exit $code
