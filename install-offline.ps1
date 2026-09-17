param([string]$PythonPath = 'python', [string]$EnvironmentPath = '.venv')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $PythonPath -c "import sys,platform; assert sys.version_info[:2]==(3,11) and platform.system()=='Windows' and platform.machine().lower() in ('amd64','x86_64'), 'This bundle requires Windows x64 Python 3.11'"
if ($LASTEXITCODE -ne 0) { throw 'Windows x64 Python 3.11 경로를 지정하세요.' }
if (Test-Path -LiteralPath $EnvironmentPath) { throw '기존 환경을 덮어쓰지 않습니다. 다른 -EnvironmentPath를 지정하세요.' }
if (-not (Test-Path -LiteralPath '.\wheelhouse')) { throw '오프라인 패키지 wheelhouse가 필요합니다.' }
& $PythonPath scripts\verify_release.py --allow-source-tree
if ($LASTEXITCODE -ne 0) { throw '배포 파일 검증 실패' }
& $PythonPath -m venv $EnvironmentPath
if ($LASTEXITCODE -ne 0) { throw '가상환경 생성 실패' }
$StationPython = Join-Path $EnvironmentPath 'Scripts\python.exe'
& $StationPython -m pip install --no-index --find-links .\wheelhouse --disable-pip-version-check -r requirements-lock-windows.txt
if ($LASTEXITCODE -ne 0) { throw '오프라인 설치 실패. 생성한 환경을 점검하세요.' }
& $StationPython -m pip check
if ($LASTEXITCODE -ne 0) { throw '패키지 의존성 검사 실패' }
& $StationPython -X utf8 scripts\doctor.py
if ($LASTEXITCODE -ne 0) { throw '설치 후 사전 검사 실패' }
Write-Output '오프라인 설치 완료. run-station.ps1로 서버를 실행하세요. 브라우저는 자동으로 열지 않습니다.'
