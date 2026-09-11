param(
    [Parameter(Mandatory = $true)]
    [string]$DataRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [string]$Domain = "web",
    [string]$Tier = "small",
    [string[]]$QuestionIds = @("05cce9b3"),
    [int]$HaystackLimit = 3,
    [switch]$AllQuestions,
    [switch]$FullHaystack,
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
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$dataRootPath = (Resolve-Path -LiteralPath $DataRoot).Path
$outputRootPath = [System.IO.Path]::GetFullPath($OutputRoot)

if (-not $FullHaystack -and $HaystackLimit -le 0) {
    throw "HaystackLimit must be positive. This script is for structural smoke tests only."
}
if (Test-Path -LiteralPath $outputRootPath) {
    throw "Refusing to overwrite existing output root: $outputRootPath"
}

function Invoke-Group {
    param(
        [string]$Name,
        [string]$Mode,
        [string]$Binary,
        [string[]]$LauncherCommand,
        [string]$VersionLabel,
        [string]$IngestPromptFile,
        [string]$DirectAnswerPromptFile
    )

    $groupRoot = Join-Path $outputRootPath $Name
    $buildDir = Join-Path $groupRoot "build"
    $evalDir = Join-Path $groupRoot "evaluate"
    $common = @(
        (Join-Path $repoRoot "evaluation\run_eval.py"),
        "--method", "codeagent_auto_memory",
        "--data-root", $dataRootPath,
        "--domain", $Domain,
        "--tier", $Tier,
        "--codeagent-auto-memory-experiment-mode", $Mode,
        "--codeagent-auto-memory-binary", $Binary,
        "--codeagent-auto-memory-version-label", $VersionLabel,
        "--codeagent-auto-memory-ingest-max-attempts", "1",
        "--codeagent-auto-memory-query-max-attempts", "1"
    )
    if (-not $AllQuestions) {
        if ($QuestionIds.Count -eq 0) { throw "QuestionIds cannot be empty unless -AllQuestions is used" }
        $common += @("--question-ids") + $QuestionIds
    }
    if (-not $FullHaystack) {
        $common += @("--haystack-limit", $HaystackLimit)
    }
    if ($IngestPromptFile) {
        $common += @("--codeagent-auto-memory-ingest-prompt-file", (Resolve-Path -LiteralPath $IngestPromptFile).Path)
    }
    if ($LauncherCommand.Count -gt 0) {
        $common += @(
            "--codeagent-auto-memory-launcher-command-json",
            (ConvertTo-Json -InputObject @($LauncherCommand) -Compress)
        )
    }
    if ($DirectAnswerPromptFile) {
        $common += @("--codeagent-auto-memory-direct-answer-prompt-file", (Resolve-Path -LiteralPath $DirectAnswerPromptFile).Path)
    }

    Write-Host "[$Name] building memory state"
    & $Python @common --output-dir $buildDir --save-memory --skip-evaluation
    if ($LASTEXITCODE -ne 0) { throw "[$Name] build failed with exit code $LASTEXITCODE" }

    Write-Host "[$Name] evaluating direct answers"
    & $Python @common --output-dir $evalDir --load-memory-dir (Join-Path $buildDir "memory_state")
    if ($LASTEXITCODE -ne 0) { throw "[$Name] evaluation failed with exit code $LASTEXITCODE" }
}

Invoke-Group -Name "memory_off" -Mode "memory_off" -Binary $MemoryOffBinary -LauncherCommand $MemoryOffLauncherCommand -VersionLabel "memory-off" -IngestPromptFile $BaselineIngestPromptFile -DirectAnswerPromptFile $BaselineDirectAnswerPromptFile
Invoke-Group -Name "baseline" -Mode "baseline" -Binary $BaselineBinary -LauncherCommand $BaselineLauncherCommand -VersionLabel $BaselineVersionLabel -IngestPromptFile $BaselineIngestPromptFile -DirectAnswerPromptFile $BaselineDirectAnswerPromptFile
Invoke-Group -Name "candidate" -Mode "candidate" -Binary $CandidateBinary -LauncherCommand $CandidateLauncherCommand -VersionLabel $CandidateVersionLabel -IngestPromptFile $CandidateIngestPromptFile -DirectAnswerPromptFile $CandidateDirectAnswerPromptFile

$comparisonDir = Join-Path $outputRootPath "comparison"
& $Python (Join-Path $repoRoot "evaluation\compare_memory_regression.py") `
    --memory-off (Join-Path $outputRootPath "memory_off\evaluate") `
    --baseline (Join-Path $outputRootPath "baseline\evaluate") `
    --candidate (Join-Path $outputRootPath "candidate\evaluate") `
    --output-dir $comparisonDir
if ($LASTEXITCODE -ne 0) { throw "Comparison failed with exit code $LASTEXITCODE" }

if ($FullHaystack) {
    Write-Host "Full-haystack regression run completed: $outputRootPath"
} else {
    Write-Host "Structural smoke run completed: $outputRootPath"
}
Write-Host "Report: $(Join-Path $comparisonDir 'report.md')"
