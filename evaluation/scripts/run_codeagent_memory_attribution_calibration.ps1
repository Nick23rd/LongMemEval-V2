param(
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][switch]$ConfirmFullHaystack,
    [string]$Python = "python",
    [switch]$Resume,
    [string]$CodeAgentModel = "",
    [int]$IngestMaxTurns = 60,
    [int]$QueryMaxTurns = 20,
    [int]$IngestMaxAttempts = 2,
    [int]$QueryMaxAttempts = 2,
    [double]$TimeoutSeconds = 1800,
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
if (-not $ConfirmFullHaystack) {
    throw "Pass -ConfirmFullHaystack: this 10-question calibration still builds two complete small-tier memory states."
}
$setPath = Join-Path $PSScriptRoot "..\calibration_sets\codeagent_memory_web_small_10.json"
$set = Get-Content (Resolve-Path $setPath) -Raw | ConvertFrom-Json
$runner = Join-Path $PSScriptRoot "run_codeagent_memory_attribution.ps1"
$invoke = @{
    DataRoot = $DataRoot; OutputRoot = $OutputRoot; Domain = $set.domain; Tier = $set.tier
    QuestionIds = [string[]]$set.question_ids; FullHaystack = $true; Resume = $Resume; Python = $Python
    CodeAgentModel = $CodeAgentModel; IngestMaxTurns = $IngestMaxTurns; QueryMaxTurns = $QueryMaxTurns
    IngestMaxAttempts = $IngestMaxAttempts; QueryMaxAttempts = $QueryMaxAttempts; TimeoutSeconds = $TimeoutSeconds
    WriterABinary = $WriterABinary; WriterBBinary = $WriterBBinary
    RecallABinary = $RecallABinary; RecallBBinary = $RecallBBinary
    WriterALauncherCommand = $WriterALauncherCommand; WriterBLauncherCommand = $WriterBLauncherCommand
    RecallALauncherCommand = $RecallALauncherCommand; RecallBLauncherCommand = $RecallBLauncherCommand
    WriterAIngestPromptFile = $WriterAIngestPromptFile; WriterBIngestPromptFile = $WriterBIngestPromptFile
    RecallAQueryPromptFile = $RecallAQueryPromptFile; RecallBQueryPromptFile = $RecallBQueryPromptFile
    RecallADirectAnswerPromptFile = $RecallADirectAnswerPromptFile
    RecallBDirectAnswerPromptFile = $RecallBDirectAnswerPromptFile
}
Write-Host "Running fixed calibration set '$($set.name)' with $($set.question_ids.Count) questions and full small haystack."
& $runner @invoke
if ($LASTEXITCODE -ne 0) { throw "Calibration run failed with exit code $LASTEXITCODE" }
