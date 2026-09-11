param(
    [Parameter(Mandatory = $true)]
    [string]$DataRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [Parameter(Mandatory = $true)]
    [switch]$ConfirmFullRun,

    [string]$Domain = "web",
    [string]$Python = "python",
    [string]$MemoryOffBinary = "codeagentcli",
    [string]$BaselineBinary = "codeagentcli",
    [string]$CandidateBinary = "codeagentcli",
    [string[]]$MemoryOffLauncherCommand = @(),
    [string[]]$BaselineLauncherCommand = @(),
    [string[]]$CandidateLauncherCommand = @(),
    [string]$BaselineVersionLabel = "baseline",
    [string]$CandidateVersionLabel = "candidate",
    [string]$BaselineIngestPromptFile = "",
    [string]$CandidateIngestPromptFile = "",
    [string]$BaselineDirectAnswerPromptFile = "",
    [string]$CandidateDirectAnswerPromptFile = ""
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmFullRun) {
    throw "Pass -ConfirmFullRun to acknowledge that full small-tier ingestion can consume substantial time and model budget."
}

$runner = Join-Path $PSScriptRoot "run_codeagent_memory_regression.ps1"
& $runner `
    -DataRoot $DataRoot `
    -OutputRoot $OutputRoot `
    -Domain $Domain `
    -Tier "small" `
    -AllQuestions `
    -FullHaystack `
    -Python $Python `
    -MemoryOffBinary $MemoryOffBinary `
    -BaselineBinary $BaselineBinary `
    -CandidateBinary $CandidateBinary `
    -MemoryOffLauncherCommand $MemoryOffLauncherCommand `
    -BaselineLauncherCommand $BaselineLauncherCommand `
    -CandidateLauncherCommand $CandidateLauncherCommand `
    -BaselineVersionLabel $BaselineVersionLabel `
    -CandidateVersionLabel $CandidateVersionLabel `
    -BaselineIngestPromptFile $BaselineIngestPromptFile `
    -CandidateIngestPromptFile $CandidateIngestPromptFile `
    -BaselineDirectAnswerPromptFile $BaselineDirectAnswerPromptFile `
    -CandidateDirectAnswerPromptFile $CandidateDirectAnswerPromptFile

if ($LASTEXITCODE -ne 0) {
    throw "Full small-tier regression failed with exit code $LASTEXITCODE"
}

