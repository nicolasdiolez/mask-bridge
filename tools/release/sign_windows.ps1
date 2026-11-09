param(
    [switch]$VerifyOnly,
    [switch]$InspectOnly,
    [string]$Executable = (Join-Path $PSScriptRoot '../../MaskBridge.lrplugin/backend/maskbridge_engine/maskbridge_engine.exe'),
    [string]$Thumbprint = $env:MASKBRIDGE_SIGNING_THUMBPRINT
)
$ErrorActionPreference = 'Stop'
$env:PSModulePath = Join-Path $PSHOME 'Modules'
try {
    $Executable = (Resolve-Path -LiteralPath $Executable).Path
    if (-not $VerifyOnly -and -not $InspectOnly) {
        if (-not $Thumbprint) { throw 'Set MASKBRIDGE_SIGNING_THUMBPRINT to an installed code-signing certificate. No password is stored in this script.' }
        $certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$Thumbprint"
        if (-not $certificate.HasPrivateKey) { throw 'The signing certificate has no private key.' }
        $signed = Set-AuthenticodeSignature -LiteralPath $Executable -Certificate $certificate -HashAlgorithm SHA256 -TimestampServer 'http://timestamp.digicert.com'
        if ($signed.Status -ne 'Valid') { throw "Signing failed: $($signed.Status)" }
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Executable
    $result = @{status=$signature.Status.ToString(); timestamped=($null -ne $signature.TimeStamperCertificate)}
    if ($InspectOnly) { $result | ConvertTo-Json -Compress; exit 0 }
    if ($signature.Status -ne 'Valid' -or -not $result.timestamped) { throw "Signature/timestamp verification failed: $($signature.Status)" }
    Write-Output 'Authenticode signature and timestamp verified.'
    exit 0
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
