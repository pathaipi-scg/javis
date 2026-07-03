# tts_windows.ps1 - Thai TTS via Windows OneCore voice (Microsoft Pattara)
# Uses WinRT Windows.Media.SpeechSynthesis -> writes a WAV file.
# Usage: powershell -File tts_windows.ps1 -InFile <utf8 text> -OutFile <wav> [-Voice <name>]
# Offline 100%, runs on CPU, no internet / no admin needed.
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads .ps1 as ANSI, so Thai
#       literals here would corrupt. The spoken text is read from -InFile as UTF-8.
param(
    [Parameter(Mandatory=$true)][string]$InFile,
    [Parameter(Mandatory=$true)][string]$OutFile,
    [string]$Voice = ""      # empty = first Thai voice found (Pattara)
)
$ErrorActionPreference = "Stop"
$text = [System.IO.File]::ReadAllText($InFile, [System.Text.Encoding]::UTF8)

Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media,ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.DataReader,Windows.Storage.Streams,ContentType=WindowsRuntime] | Out-Null

# helper to await a WinRT IAsyncOperation (PS5.1 has no direct await)
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
                   $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $t) { $m = $asTask.MakeGenericMethod($t); $task = $m.Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }

$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$all = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
if ($Voice) {
    $v = $all | Where-Object { $_.DisplayName -eq $Voice } | Select-Object -First 1
} else {
    $v = $all | Where-Object { $_.Language -like "th*" } | Select-Object -First 1   # first Thai voice
}
if (-not $v) { throw "No Thai voice installed (install Thai speech first)" }
$synth.Voice = $v

$stream = Await($synth.SynthesizeTextToStreamAsync($text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$size = $stream.Size
$reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
Await($reader.LoadAsync($size)) ([uint32]) | Out-Null
$bytes = New-Object byte[] $size
$reader.ReadBytes($bytes)
[System.IO.File]::WriteAllBytes($OutFile, $bytes)
