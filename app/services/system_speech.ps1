$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    while ($null -ne ($line = [Console]::ReadLine())) {
        try {
            $request = $line | ConvertFrom-Json
            if ($request.operation -eq 'voices') {
                $voices = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {
                    @{ name = $_.VoiceInfo.Name; language = $_.VoiceInfo.Culture.Name }
                })
                $result = @{ voices = $voices }
            } elseif ($request.operation -eq 'check') {
                $synth.SelectVoice([string]$request.voice)
                $result = @{ ready = $true }
            } else {
                $synth.SelectVoice([string]$request.voice)
                $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
                    24000,
                    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
                    [System.Speech.AudioFormat.AudioChannel]::Mono)
                $synth.SetOutputToWaveFile([string]$request.output, $format)
                $synth.Speak([string]$request.text)
                $synth.SetOutputToNull()
                $result = @{ ready = $true }
            }
            [Console]::WriteLine((ConvertTo-Json -InputObject $result -Compress -Depth 4))
        } catch {
            $synth.SetOutputToNull()
            [Console]::WriteLine((ConvertTo-Json -InputObject @{ error = $_.Exception.Message } -Compress))
        }
    }
} finally { $synth.Dispose() }
