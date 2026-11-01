param([string]$Root = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
try {
    $Root = (Resolve-Path -LiteralPath $Root).Path
    $manifestPath = Join-Path $Root 'snapshot-manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1) { throw 'Unsupported manifest schema' }
    $expected = @{}
    foreach ($entry in $manifest.files) {
        $name = [string]$entry.path
        if (!$name -or $name.Contains('\') -or $name.StartsWith('/') -or
            $name.Contains(':') -or ($name.Split('/') -contains '..') -or
            $name -eq 'snapshot-manifest.json' -or $expected.ContainsKey($name)) {
            throw "Invalid manifest path: $name"
        }
        $expected[$name] = $entry
    }
    $seen = @{}
    $directories = @{}
    foreach ($name in $manifest.directories) { $directories[[string]$name] = $true }
    $seenDirectories = @{}
    $errors = [System.Collections.Generic.List[string]]::new()
    foreach ($file in Get-ChildItem -LiteralPath $Root -Recurse -Force) {
        if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point refused: $($file.FullName)" }
        $name = $file.FullName.Substring($Root.Length).TrimStart('\','/').Replace('\','/')
        if ($file.PSIsContainer) {
            if (!$directories.ContainsKey($name)) { $errors.Add("EXTRA DIRECTORY: $name") }
            $seenDirectories[$name] = $true
            continue
        }
        if ($name -eq 'snapshot-manifest.json') { continue }
        if (!$expected.ContainsKey($name)) { $errors.Add("EXTRA: $name"); continue }
        $seen[$name] = $true
        $entry = $expected[$name]
        if ($file.Length -ne [long]$entry.bytes) { $errors.Add("SIZE: $name"); continue }
        # User instruction: never hash ISO inputs or generated ISO images.
        if ($name -match '(?i)\.iso(?:\.partial)?$') { continue }
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -cne [string]$entry.sha256) { $errors.Add("SHA256: $name") }
    }
    foreach ($name in $expected.Keys) { if (!$seen.ContainsKey($name)) { $errors.Add("MISSING: $name") } }
    foreach ($name in $directories.Keys) { if (!$seenDirectories.ContainsKey($name)) { $errors.Add("MISSING DIRECTORY: $name") } }
    if ($errors.Count) { throw ($errors -join [Environment]::NewLine) }
    Write-Host "PASS: $($expected.Count) files; paths and sizes match; non-ISO file digests match. ISO hashing is prohibited."
    exit 0
} catch {
    Write-Error -Message $_ -ErrorAction Continue
    exit 1
}
