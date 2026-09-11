param(
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][switch]$ConfirmFullRun,
    [string]$Domain = "web",
    [string]$Python = "python",
    [string]$WriterABinary = "codeagentcli",
    [string]$WriterBBinary = "codeagentcli",
    [string]$RecallABinary = "codeagentcli",
    [string]$RecallBBinary = "codeagentcli",
    [string[]]$WriterALauncherCommand = @(),
    [string[]]$WriterBLauncherCommand = @(),
    [string[]]$RecallALauncherCommand = @(),
    [string[]]$RecallBLauncherCommand = @(),
    [string]$WriterAIngestPromptFile = "",
    [string]$WriterBIngestPromptFile = "",
    [string]$RecallAQueryPromptFile = "",
    [string]$RecallBQueryPromptFile = "",
    [string]$RecallADirectAnswerPromptFile = "",
    [string]$RecallBDirectAnswerPromptFile = ""
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmFullRun) { throw "Pass -ConfirmFullRun to acknowledge the full small-tier 2x2 run cost." }
$runner = Join-Path $PSScriptRoot "run_codeagent_memory_attribution.ps1"
& $runner -DataRoot $DataRoot -OutputRoot $OutputRoot -Domain $Domain -Tier "small" -AllQuestions -FullHaystack `
    -Python $Python -WriterABinary $WriterABinary -WriterBBinary $WriterBBinary `
    -RecallABinary $RecallABinary -RecallBBinary $RecallBBinary `
    -WriterALauncherCommand $WriterALauncherCommand -WriterBLauncherCommand $WriterBLauncherCommand `
    -RecallALauncherCommand $RecallALauncherCommand -RecallBLauncherCommand $RecallBLauncherCommand `
    -WriterAIngestPromptFile $WriterAIngestPromptFile -WriterBIngestPromptFile $WriterBIngestPromptFile `
    -RecallAQueryPromptFile $RecallAQueryPromptFile -RecallBQueryPromptFile $RecallBQueryPromptFile `
    -RecallADirectAnswerPromptFile $RecallADirectAnswerPromptFile -RecallBDirectAnswerPromptFile $RecallBDirectAnswerPromptFile
if ($LASTEXITCODE -ne 0) { throw "Full small-tier attribution failed with exit code $LASTEXITCODE" }
