# Agent hub: wire this agent/app into Langfuse (own project, keys, evals, ratings, LLM gateway).
# $env:LF_TOKEN='<token>'; $env:LF_NAME='<agent-name>'; irm {{BASE}}/install.ps1 | iex
$ErrorActionPreference = 'Stop'
$Base = '{{BASE}}'
if (-not $env:LF_TOKEN) { throw 'Set $env:LF_TOKEN (the enroll token)' }
$Name = ($(if ($env:LF_NAME) { $env:LF_NAME } else { Split-Path -Leaf (Get-Location) })) -replace '[^A-Za-z0-9._-]', ''
$Dir = $(if ($env:LF_DIR) { $env:LF_DIR } else { (Get-Location).Path })
$EnvFile = Join-Path $Dir '.env'
New-Item -ItemType Directory -Force $Dir | Out-Null

$r = Invoke-RestMethod -Method Post -Uri "$Base/v1/enroll" -Headers @{ Authorization = "Bearer $env:LF_TOKEN" } `
  -ContentType 'application/json' -Body (@{ name = $Name } | ConvertTo-Json)
$vals = $r.env
$keys = $vals.PSObject.Properties.Name

$lines = @()
if (Test-Path $EnvFile) {
  Copy-Item $EnvFile "$EnvFile.pre-langfuse.bak" -Force
  $lines = Get-Content $EnvFile | Where-Object { $_ -notmatch ('^(export )?(' + ($keys -join '|') + ')=|^# Langfuse \+ LLM gateway') }
}
$lines += "# Langfuse + LLM gateway (agent hub $(Get-Date -Format yyyy-MM-dd); setup: $($r.setup -join ', '))"
$lines += $keys | ForEach-Object { "$_=$($vals.$_)" }
Set-Content -Path $EnvFile -Value $lines -Encoding utf8NoBOM
if (git -C $Dir rev-parse --git-dir 2>$null) {
  foreach ($p in '.env', '.env.pre-langfuse.bak') {
    git -C $Dir check-ignore -q $p; if ($LASTEXITCODE -ne 0) { Add-Content (Join-Path $Dir '.gitignore') $p }
  }
}

$auth = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("$($vals.LANGFUSE_PUBLIC_KEY):$($vals.LANGFUSE_SECRET_KEY)"))
$id = "smoke-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())-$PID"
$batch = @{ batch = @(@{ id = "$id-e"; type = 'trace-create'; timestamp = (Get-Date).ToUniversalTime().ToString('o')
  body = @{ id = $id; name = 'hub-smoke'; tags = @('smoke', $Name); input = 'What is the capital of France?'; output = 'Paris is the capital of France.' } }) }
$s1 = (Invoke-WebRequest -Method Post -Uri "$($vals.LANGFUSE_HOST)/api/public/ingestion" -Headers @{ Authorization = $auth } `
  -ContentType 'application/json' -Body ($batch | ConvertTo-Json -Depth 6)).StatusCode
$chat = @{ model = $vals.LLM_MODEL; max_tokens = 256; messages = @(@{ role = 'user'; content = 'Reply with: hub connected' }) }
try {
  $s2 = (Invoke-WebRequest -Method Post -Uri "$($vals.LLM_BASE_URL)/chat/completions" -Headers @{ Authorization = "Bearer $($vals.LLM_API_KEY)" } `
    -ContentType 'application/json' -Body ($chat | ConvertTo-Json -Depth 5)).StatusCode
} catch { $s2 = $_.Exception.Response.StatusCode.value__ }

$h = $vals.LANGFUSE_HOST; $p = $vals.LANGFUSE_PROJECT_ID
"Langfuse project : $Name ($h/project/$p)"
"Keys written to  : $EnvFile (gitignored; values not shown)"
"Smoke trace      : HTTP $s1 -> $h/project/$p/traces/$id"
"Gateway LLM call : HTTP $s2 (appears under Traces in ~1 min)"
"Next             : read $Base/ and wire your code (section 2)."
