# Cria o atalho "Central de Cameras" (icone da Central) que abre o PAINEL.bat,
# na Area de Trabalho e no menu Iniciar. Chamado pelo CRIAR_ATALHO.bat.
param([string]$Pasta)
$ErrorActionPreference = 'Stop'
if (-not $Pasta) { $Pasta = Split-Path -Parent $PSScriptRoot }
$Pasta = (Resolve-Path $Pasta).Path
$alvo  = Join-Path $Pasta 'PAINEL.bat'
$icone = Join-Path $Pasta 'app\icone.ico'
if (-not (Test-Path $alvo))  { throw "nao achei $alvo" }
if (-not (Test-Path $icone)) { throw "nao achei $icone" }
$ws = New-Object -ComObject WScript.Shell
$ok = 0
foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    if (-not $d -or -not (Test-Path $d)) { continue }
    $a = $ws.CreateShortcut((Join-Path $d 'Central de Cameras.lnk'))
    $a.TargetPath = $alvo
    $a.WorkingDirectory = $Pasta
    $a.IconLocation = "$icone,0"
    $a.Description = 'Central de Cameras'
    $a.WindowStyle = 7
    $a.Save()
    Write-Host "  [OK] $d"
    $ok++
}
if ($ok -eq 0) { throw 'nenhuma pasta de destino encontrada' }
