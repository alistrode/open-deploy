param([string]$Destination='E:\OpenDeploy-PXVIRT.iso')
$ErrorActionPreference='Stop'
if($Destination -cne 'E:\OpenDeploy-PXVIRT.iso') { throw 'Use the requested E: ISO pathname.' }
if(Test-Path -LiteralPath $Destination) { throw 'An ISO already exists; it has been preserved.' }
$lock=Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\dependencies.lock.json') -Raw | ConvertFrom-Json
$expected=[long]$lock.pxvirt.bytes
$partial=$Destination+'.partial'
$sources=@(
    'https://mirrors.lierfang.com/pxcloud/pxvirt/isos/pxvirt-8.4-2-amd64.iso',
    [string]$lock.pxvirt.url
) | Select-Object -Unique
foreach($source in $sources) {
    for($attempt=0;$attempt -lt 8;$attempt++) {
        $before=if(Test-Path -LiteralPath $partial){[long](Get-Item -LiteralPath $partial).Length}else{0L}
        if($before -gt $expected) { throw 'The preserved partial file is larger than the pinned source.' }
        & curl.exe --http1.1 -L --fail --connect-timeout 15 --max-time 3600 `
            --speed-limit 1000000 --speed-time 20 -C - --output $partial $source
        $code=$LASTEXITCODE
        $after=if(Test-Path -LiteralPath $partial){[long](Get-Item -LiteralPath $partial).Length}else{0L}
        if($code -eq 0 -and $after -eq $expected) {
            Move-Item -LiteralPath $partial -Destination $Destination
            @{path=$Destination;bytes=$after;source=$source} | ConvertTo-Json -Compress
            return
        }
        # Only a truncated/reset transfer that made progress is resumed at the
        # same source. Slow transfers (curl 28) switch sources immediately.
        if($code -notin @(18,56) -or $after -le $before) { break }
    }
    Write-Output 'Trying the next pinned-version source; the partial ISO is retained.'
}
throw 'Available direct sources did not complete at the requested rate; the partial ISO was preserved.'
