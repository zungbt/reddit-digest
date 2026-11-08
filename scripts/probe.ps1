# Probe Reddit feed options once. Run: powershell -ExecutionPolicy Bypass -File scripts\probe.ps1
# Writes raw responses + summary to work\probe\. Waits per x-ratelimit-reset between requests.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$out = Join-Path $root 'work\probe'
New-Item -ItemType Directory -Force $out | Out-Null
$ua = 'reddit-digest/0.1'
$doh = 'https://cloudflare-dns.com/dns-query'
$summary = Join-Path $out 'summary.txt'
Set-Content $summary "probe $(Get-Date -Format s)" -Encoding utf8

$tests = @(
  @{ name = 'search_flair'; url = 'https://www.reddit.com/r/LocalLLaMA/search.rss?q=flair%3A%22New%20Model%22&restrict_sr=1&sort=new&limit=100' },
  @{ name = 'domain_github'; url = 'https://www.reddit.com/domain/github.com/new/.rss?limit=100' },
  @{ name = 'multi_sub'; url = 'https://www.reddit.com/r/embedded+FPGA+esp32/new/.rss?limit=100' },
  @{ name = 'json_LocalLLaMA'; url = 'https://www.reddit.com/r/LocalLLaMA/new.json?limit=100' },
  @{ name = 'json_LocalLLM'; url = 'https://www.reddit.com/r/LocalLLM/new.json?limit=100' },
  @{ name = 'json_ClaudeCode'; url = 'https://www.reddit.com/r/ClaudeCode/new.json?limit=100' },
  @{ name = 'json_embedded'; url = 'https://www.reddit.com/r/embedded/new.json?limit=100' },
  @{ name = 'json_TopologyAI'; url = 'https://www.reddit.com/r/TopologyAI/new.json?limit=100' },
  @{ name = 'json_IndieDev'; url = 'https://www.reddit.com/r/IndieDev/new.json?limit=100' }
)

$wait = 0
foreach ($t in $tests) {
  if ($wait -gt 0) { Write-Host "waiting $wait s"; Start-Sleep $wait }
  $body = Join-Path $out "$($t.name).body"
  $hdr = Join-Path $out "$($t.name).hdr"
  curl.exe -s --doh-url $doh -A $ua -D $hdr -o $body $t.url
  $h = Get-Content $hdr -Raw
  $code = if ($h -match 'HTTP/\S+ (\d+)') { $Matches[1] } else { '000' }
  $ctype = if ($h -match '(?im)^content-type:\s*(.+)$') { $Matches[1].Trim() } else { '' }
  $reset = if ($h -match '(?im)^x-ratelimit-reset:\s*(\d+)') { [int]$Matches[1] } else { 60 }
  $remaining = if ($h -match '(?im)^x-ratelimit-remaining:\s*([\d.]+)') { [double]$Matches[1] } else { 0 }
  $wait = if ($remaining -ge 1) { 2 } else { $reset + 2 }
  if ($code -eq '429') { $wait = [Math]::Max($reset, 60) + 2 }

  $line = "$($t.name): code=$code type=$ctype remaining=$remaining reset=$reset"
  $raw = if (Test-Path $body) { Get-Content $body -Raw -Encoding utf8 } else { '' }
  if ($code -eq '200' -and $ctype -like '*atom*') {
    $line += " entries=$(([regex]::Matches($raw, '<entry>')).Count)"
  } elseif ($code -eq '200' -and $ctype -like '*json*') {
    $posts = (ConvertFrom-Json $raw).data.children | ForEach-Object { $_.data }
    $line += " posts=$($posts.Count)"
    $flairs = $posts | Group-Object { if ($_.link_flair_text) { $_.link_flair_text } else { '(none)' } } |
      Sort-Object Count -Descending | ForEach-Object { "$($_.Count) x $($_.Name)" }
    $line += "`n  flairs: " + ($flairs -join ' | ')
  }
  Write-Host $line
  Add-Content $summary $line -Encoding utf8
}
Write-Host "done -> $summary"
