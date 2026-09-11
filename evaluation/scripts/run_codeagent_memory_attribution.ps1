param(
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$Domain = "web",
    [string]$Tier = "small",
    [string[]]$QuestionIds = @("05cce9b3"),
    [int]$HaystackLimit = 3,
    [switch]$AllQuestions,
    [switch]$FullHaystack,
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
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$dataRootPath = (Resolve-Path -LiteralPath $DataRoot).Path
$outputRootPath = [System.IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $outputRootPath) { throw "Refusing to overwrite existing output root: $outputRootPath" }
if (-not $FullHaystack -and $HaystackLimit -le 0) { throw "HaystackLimit must be positive" }

function Resolve-Launcher([string[]]$Command, [string]$Binary) {
    if ($Command.Count -gt 0) { return @($Command) }
    return @($Binary)
}

$writerA = Resolve-Launcher $WriterALauncherCommand $WriterABinary
$writerB = Resolve-Launcher $WriterBLauncherCommand $WriterBBinary
$recallA = Resolve-Launcher $RecallALauncherCommand $RecallABinary
$recallB = Resolve-Launcher $RecallBLauncherCommand $RecallBBinary

function Get-CommonArgs([string]$Mode, [string[]]$Writer, [string]$IngestPromptFile) {
    $argsList = @(
        (Join-Path $repoRoot "evaluation\run_eval.py"), "--method", "codeagent_auto_memory",
        "--data-root", $dataRootPath, "--domain", $Domain, "--tier", $Tier,
        "--codeagent-auto-memory-experiment-mode", $Mode,
        "--codeagent-auto-memory-launcher-command-json", (ConvertTo-Json -InputObject @($Writer) -Compress),
        "--codeagent-auto-memory-ingest-launcher-command-json", (ConvertTo-Json -InputObject @($Writer) -Compress),
        "--codeagent-auto-memory-ingest-max-attempts", "1", "--codeagent-auto-memory-query-max-attempts", "1"
    )
    if (-not $AllQuestions) {
        if ($QuestionIds.Count -eq 0) { throw "QuestionIds cannot be empty unless -AllQuestions is used" }
        $argsList += @("--question-ids") + $QuestionIds
    }
    if (-not $FullHaystack) { $argsList += @("--haystack-limit", $HaystackLimit) }
    if ($IngestPromptFile) { $argsList += @("--codeagent-auto-memory-ingest-prompt-file", (Resolve-Path -LiteralPath $IngestPromptFile).Path) }
    return $argsList
}

function Build-Memory([string]$Name, [string]$Mode, [string[]]$Writer, [string]$IngestPromptFile) {
    $buildDir = Join-Path $outputRootPath "$Name\build"
    $argsList = Get-CommonArgs $Mode $Writer $IngestPromptFile
    Write-Host "[$Name] building frozen memory"
    & $Python @argsList --output-dir $buildDir --save-memory --skip-evaluation
    if ($LASTEXITCODE -ne 0) { throw "[$Name] build failed with exit code $LASTEXITCODE" }
}

function Evaluate-Cell(
    [string]$Cell, [string]$WriterName, [string]$Mode, [string[]]$Writer,
    [string]$IngestPromptFile, [string[]]$Recall, [string]$QueryPromptFile,
    [string]$DirectAnswerPromptFile
) {
    $argsList = Get-CommonArgs $Mode $Writer $IngestPromptFile
    $argsList += @(
        "--codeagent-auto-memory-query-launcher-command-json", (ConvertTo-Json -InputObject @($Recall) -Compress),
        "--codeagent-auto-memory-allow-query-override-on-load"
    )
    if ($QueryPromptFile) { $argsList += @("--codeagent-auto-memory-query-prompt-file", (Resolve-Path -LiteralPath $QueryPromptFile).Path) }
    if ($DirectAnswerPromptFile) { $argsList += @("--codeagent-auto-memory-direct-answer-prompt-file", (Resolve-Path -LiteralPath $DirectAnswerPromptFile).Path) }
    $evalDir = Join-Path $outputRootPath "$Cell\evaluate"
    $stateDir = Join-Path $outputRootPath "$WriterName\build\memory_state"
    Write-Host "[$Cell] evaluating frozen $WriterName memory"
    & $Python @argsList --output-dir $evalDir --load-memory-dir $stateDir
    if ($LASTEXITCODE -ne 0) { throw "[$Cell] evaluation failed with exit code $LASTEXITCODE" }
}

Build-Memory "writer_a" "baseline" $writerA $WriterAIngestPromptFile
Build-Memory "writer_b" "candidate" $writerB $WriterBIngestPromptFile
Evaluate-Cell "aa" "writer_a" "baseline" $writerA $WriterAIngestPromptFile $recallA $RecallAQueryPromptFile $RecallADirectAnswerPromptFile
Evaluate-Cell "ab" "writer_a" "baseline" $writerA $WriterAIngestPromptFile $recallB $RecallBQueryPromptFile $RecallBDirectAnswerPromptFile
Evaluate-Cell "ba" "writer_b" "candidate" $writerB $WriterBIngestPromptFile $recallA $RecallAQueryPromptFile $RecallADirectAnswerPromptFile
Evaluate-Cell "bb" "writer_b" "candidate" $writerB $WriterBIngestPromptFile $recallB $RecallBQueryPromptFile $RecallBDirectAnswerPromptFile

$reportDir = Join-Path $outputRootPath "attribution"
& $Python (Join-Path $repoRoot "evaluation\compare_memory_attribution.py") `
    --aa (Join-Path $outputRootPath "aa\evaluate") --ab (Join-Path $outputRootPath "ab\evaluate") `
    --ba (Join-Path $outputRootPath "ba\evaluate") --bb (Join-Path $outputRootPath "bb\evaluate") `
    --output-dir $reportDir
if ($LASTEXITCODE -ne 0) { throw "Attribution comparison failed with exit code $LASTEXITCODE" }
Write-Host "Attribution report: $(Join-Path $reportDir 'report.md')"
