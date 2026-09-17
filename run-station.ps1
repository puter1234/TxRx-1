param([string]$PythonPath = '', [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $PythonPath) {
    foreach ($Candidate in @('.\.venv\Scripts\python.exe', '.\.venv-offline-verified\Scripts\python.exe')) {
        if (Test-Path -LiteralPath $Candidate) { $PythonPath = $Candidate; break }
    }
}
if (-not $PythonPath) { throw 'install-offline.ps1로 먼저 로컬 환경을 설치하세요.' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw '설치한 Python 실행 경로를 -PythonPath로 지정하세요.' }
& $PythonPath -X utf8 scripts\doctor.py
if ($LASTEXITCODE -ne 0) { throw '실행 전 검사를 통과하지 못했습니다.' }
# Browser launch is deliberately manual.
& $PythonPath -X utf8 -m station --port $Port
exit $LASTEXITCODE
