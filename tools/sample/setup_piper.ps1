# Piper 러시아어 음성 내려받기 — 처음 한 번만.
#
# Piper는 슈퍼토닉과 성격이 같다: ONNX 파일을 받아 로컬 CPU에서 돌린다. API 키가
# 없고, 라이선스가 MIT라 용역 산출물에 그대로 써도 된다.
# (슈퍼토닉-3는 한국어 전용이라 러시아어 샘플을 못 만든다.)
#
# 목소리를 바꾸려면 아래 Voice 만 고치면 된다:
#   irina(여) · denis(남) · dmitri(남) · ruslan(남)

$ErrorActionPreference = "Stop"
$Voice = "irina"

$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest  = Join-Path $here "assets\piper"
New-Item -ItemType Directory -Force $dest | Out-Null

$base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/$Voice/medium"
$stem = "ru_RU-$Voice-medium"

foreach ($f in @("$stem.onnx", "$stem.onnx.json")) {
  $out = Join-Path $dest $f
  if (Test-Path $out) { Write-Host "  이미 있음 - $f"; continue }
  Write-Host "  받는 중 - $f"
  Invoke-WebRequest -Uri "$base/$f" -OutFile $out
}

# piper 실행 파일. 파이썬 패키지(piper-tts)는 윈도에서 phonemize 빌드가 자주 막혀서
# 배포된 실행 파일을 쓰는 쪽이 확실하다.
$exe = Join-Path $dest "piper\piper.exe"
if (Test-Path $exe) {
  Write-Host "  이미 있음 - piper.exe"
} else {
  $zipUrl = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
  $zip = Join-Path $dest "piper_windows.zip"
  Write-Host "  받는 중 - piper_windows_amd64.zip"
  Invoke-WebRequest -Uri $zipUrl -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $dest -Force
  Remove-Item $zip
}

Write-Host ""
Write-Host "완료 - $dest"
Write-Host "다음: python tools\sample\t1_tts.py <script.json 이 있는 폴더>"
