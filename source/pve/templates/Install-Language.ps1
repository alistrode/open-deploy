function Install-OpenDeployLanguage([string]$Language) {
    if (!$Language) { return $false }
    if ($Language -ne 'zh-CN') { throw 'Unsupported offline display language' }
    $receipt = Join-Path $Root 'language-completed.json'
    if (Test-Path -LiteralPath $receipt) {
        if ((Get-Content $receipt -Raw | ConvertFrom-Json).language -cne $Language) { throw 'Saved display language differs' }
        return $false
    }
    $packages = Join-Path $Root 'Language\zh-CN'
    $esd = Join-Path $packages 'Microsoft-Windows-Client-LanguagePack-Package_zh-cn-amd64-zh-cn.esd'
    $basic = Join-Path $packages 'Microsoft-Windows-LanguageFeatures-Basic-zh-cn-Package-amd64.cab'
    if (!(Test-Path $esd) -or !(Test-Path $basic)) { throw 'Offline Chinese packages are missing from the deployment seed' }
    $expanded = Join-Path $Root 'Language\expanded'
    New-Item -ItemType Directory -Path $expanded -Force | Out-Null
    if (!(Test-Path (Join-Path $expanded 'update.mum'))) {
        $apply = Start-Process dism.exe -ArgumentList @('/Apply-Image',('/ImageFile:"'+$esd+'"'),'/Index:1',('/ApplyDir:"'+$expanded+'"'),('/LogPath:"'+$Root+'\language-apply.log"')) -Wait -PassThru
        if ($apply.ExitCode -ne 0) { throw "Language package expansion failed: $($apply.ExitCode)" }
    }
    $uiReceipt = Join-Path $Root 'language-ui-installed.json'
    if (!(Test-Path -LiteralPath $uiReceipt)) {
        $installed = @(Get-WindowsPackage -Online | Where-Object {
            $_.PackageName -like 'Microsoft-Windows-Client-LanguagePack-Package*~zh-CN~*' -and
            $_.PackageState -in @('Installed','InstallPending')
        })
        if (!$installed.Count) {
            $install = Start-Process dism.exe -ArgumentList @('/Online','/Add-Package',('/PackagePath:"'+$expanded+'"'),'/NoRestart',('/LogPath:"'+$Root+'\language-install.log"')) -Wait -PassThru
            if ($install.ExitCode -notin @(0,3010)) { throw "Offline Chinese UI package installation failed: $($install.ExitCode)" }
        }
        Set-WinSystemLocale -SystemLocale zh-CN
        @{language='zh-CN';completedAt=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content $uiReceipt -Encoding UTF8
    }
    # Let setup finish and activate the UI package before adding the basic FOD.
    $state = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Setup\State').ImageState
    if ($state -ne 'IMAGE_STATE_COMPLETE') { return $true }
    $canonical = Join-Path $packages 'Microsoft-Windows-LanguageFeatures-Basic-zh-cn-Package~31bf3856ad364e35~amd64~~.cab'
    if (!(Test-Path -LiteralPath $canonical)) { New-Item -ItemType HardLink -Path $canonical -Value $basic | Out-Null }
    # LimitAccess forbids Windows Update fallback when local FOD resolution fails.
    $result = Add-WindowsCapability -Online -Name 'Language.Basic~~~zh-CN~0.0.1.0' -Source $packages -LimitAccess -ErrorAction Stop
    @{language='zh-CN';completedAt=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content ($receipt+'.new') -Encoding UTF8
    Move-Item -LiteralPath ($receipt+'.new') -Destination $receipt -Force
    return [bool]$result.RestartNeeded
}
