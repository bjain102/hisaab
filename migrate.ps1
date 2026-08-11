
# Run pending schema migrations against the real DB, with a checkpoint backup
# taken up front even when nothing is pending (a restore point per manual run).
Push-Location $PSScriptRoot
python -c "from app import DB_PATH; from db import migrate, get_version; applied = migrate(DB_PATH, checkpoint=True); print('applied:', applied if applied else 'none - already up to date'); print('schema version:', get_version(DB_PATH))"
$code = $LASTEXITCODE
Pop-Location
exit $code
