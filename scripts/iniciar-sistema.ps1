# Sobe o Sales Engine (Docker/Postgres + PM2 com API, worker e gateway) e abre o navegador.
# Seguro para rodar de novo a qualquer momento: NÃO reinicia o que já está rodando; só sobe o que estiver parado ou faltando.
# Uso: duplo clique em iniciar-sistema.bat.
param([switch]$NaoAbrirNavegador)

$ErrorActionPreference = "Stop"
$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz
$Url = "http://127.0.0.1:8000"
$Container = "sales-engine-db"
$Processos = @("sales-api", "sales-worker", "sales-gateway")

function Passo($t)  { Write-Host "`n>> $t" -ForegroundColor Cyan }
function Ok($t)     { Write-Host "   OK  $t" -ForegroundColor Green }
function Aviso($t)  { Write-Host "   !!  $t" -ForegroundColor Yellow }
function Parar($t)  { Write-Host "`n   ERRO  $t" -ForegroundColor Red; exit 1 }

function Esperar([scriptblock]$Condicao, [int]$Segundos, [string]$Mensagem) {
    $fim = (Get-Date).AddSeconds($Segundos)
    while ((Get-Date) -lt $fim) {
        try { if (& $Condicao) { return $true } } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

Write-Host "=== Sales Engine: iniciando ===" -ForegroundColor White

# ---------------------------------------------------------------- 1) Docker
Passo "Docker"
function DockerPronto { docker info *> $null; return ($LASTEXITCODE -eq 0) }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Parar "Docker não encontrado. Instale o Docker Desktop e rode este atalho de novo." }
if (-not (DockerPronto)) {
    Aviso "Docker não está rodando. Tentando abrir o Docker Desktop (pode levar 1 a 2 minutos)..."
    $exe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $exe) { Start-Process $exe | Out-Null }
    if (-not (Esperar { DockerPronto } 150)) {
        Parar "O Docker não ficou pronto a tempo. Abra o Docker Desktop, espere ele terminar de carregar e rode este atalho de novo."
    }
}
Ok "Docker rodando"

# ---------------------------------------------------------------- 2) Postgres
Passo "Banco de dados (container $Container)"
$estado = (docker inspect -f "{{.State.Running}}" $Container 2>$null)
if ($LASTEXITCODE -ne 0) { Parar "Container '$Container' não existe. Crie-o conforme o README (docker run ... postgres:16)." }
if ($estado -ne "true") { docker start $Container | Out-Null }
if (-not (Esperar { docker exec $Container pg_isready -U postgres *> $null; $LASTEXITCODE -eq 0 } 60)) {
    Parar "O Postgres não ficou pronto em 60 s. Veja: docker logs $Container"
}
Ok "Postgres pronto"

# ---------------------------------------------------------------- 3) PM2
Passo "PM2"
$pm2 = (Get-Command pm2.cmd -ErrorAction SilentlyContinue).Source
if (-not $pm2) { $pm2 = (Get-Command pm2 -ErrorAction SilentlyContinue).Source }
if (-not $pm2 -and $env:APPDATA) { $c = Join-Path $env:APPDATA "npm\pm2.cmd"; if (Test-Path $c) { $pm2 = $c } }
if (-not $pm2) { Parar "PM2 não encontrado. Instale uma vez com:  npm install -g pm2   (veja docs\pm2.md)" }

# gateway precisa estar compilado
if (-not (Test-Path (Join-Path $Raiz "services\whatsapp-gateway\dist\src\index.js"))) {
    Aviso "Gateway ainda não compilado: compilando (uma vez)..."
    Push-Location (Join-Path $Raiz "services\whatsapp-gateway")
    try { npm run build | Out-Null; if ($LASTEXITCODE -ne 0) { Parar "Falha ao compilar o gateway (npm run build)." } } finally { Pop-Location }
}

function EstadoDoProcesso($nome) {
    # `pm2 pid <nome>` imprime o pid quando o processo está no ar e nada quando está parado/ausente (evita parsear o JSON grande do jlist).
    $saida = (& $pm2 pid $nome 2>$null | Out-String).Trim()
    if ($saida -match '^\d+$' -and [int]$saida -gt 0) { return "online" } else { return "" }
}

foreach ($nome in $Processos) {
    $st = EstadoDoProcesso $nome
    if ($st -eq "online") { Ok "$nome já estava rodando (não foi reiniciado)"; continue }
    Aviso "$nome não está rodando: subindo..."
    & $pm2 start (Join-Path $Raiz "ecosystem.config.cjs") --only $nome | Out-Null
    if ($LASTEXITCODE -ne 0) { Aviso "Não consegui subir $nome (veja: pm2 logs $nome)" } else { Ok "$nome iniciado" }
}

# ---------------------------------------------------------------- 4) Espera a API e abre o navegador
Passo "Aguardando a API responder"
$pronta = Esperar { (Invoke-WebRequest -UseBasicParsing -Uri "$Url/api/v1/health" -TimeoutSec 3).StatusCode -eq 200 } 60
if (-not $pronta) {
    & $pm2 status
    Write-Host ""
    if (Test-Path (Join-Path $Raiz "logs\api.err.log")) { Get-Content (Join-Path $Raiz "logs\api.err.log") -Tail 15 }
    Parar "A API não respondeu em 60 s. Veja as últimas linhas do log acima (ou: pm2 logs sales-api)."
}
Ok "API respondendo em $Url"

Write-Host ""
& $pm2 status
if (-not $NaoAbrirNavegador) { Start-Process $Url }
Write-Host "`nTudo no ar. Esta janela fecha sozinha em alguns segundos." -ForegroundColor Green
Start-Sleep -Seconds 6
exit 0
