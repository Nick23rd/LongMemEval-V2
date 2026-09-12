#!/usr/bin/env node
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "../..");
let dryRun = false;

function fail(message) {
  console.error(`error: ${message}`);
  process.exit(2);
}

function parseArgs(argv) {
  const options = { _: [] };
  const booleans = new Set([
    "all-questions", "full-haystack", "confirm-full-run", "confirm-full-haystack", "resume", "dry-run", "help",
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      options._.push(token);
      continue;
    }
    const [rawKey, inline] = token.slice(2).split(/=(.*)/s, 2);
    if (booleans.has(rawKey)) {
      options[rawKey] = true;
      continue;
    }
    const value = inline ?? argv[++index];
    if (value === undefined || value.startsWith("--")) fail(`--${rawKey} requires a value`);
    if (rawKey === "question-id") (options[rawKey] ??= []).push(value);
    else options[rawKey] = value;
  }
  return options;
}

function usage() {
  console.log(`Cross-platform CodeAgent memory evaluation runner

Usage:
  node evaluation/scripts/run_codeagent_memory_eval.mjs attribution --preset calibration [options]
  node evaluation/scripts/run_codeagent_memory_eval.mjs attribution --preset small [options]
  node evaluation/scripts/run_codeagent_memory_eval.mjs regression --preset small [options]

Required:
  --data-root PATH                 Prepared LongMemEval-V2 data root
  --output-root PATH               New output root (or existing root with --resume)

Launcher values are JSON argv arrays:
  --writer-a-launcher '["/opt/codeagent-before/codeagentcli"]'
  --writer-b-launcher '["bun","/src/CodeAgent/src/cli.ts"]'

Common options:
  --python PATH                    Auto-detected from .venv when omitted
  --model NAME                     CodeAgent model; omit to use its configured default
  --runtime NAME                   Memory environment dialect: codeagent (default) or free_code
  --ingest-max-turns N             Default 60
  --query-max-turns N              Default 20
  --ingest-max-attempts N          Default 2
  --query-max-attempts N           Default 2
  --timeout-seconds N              Default 1800
  --resume                         Continue checkpoints and skip completed stages
  --dry-run                        Print all child commands without running them
  --confirm-full-haystack          Required for calibration preset
  --confirm-full-run               Required for small preset
`);
}

function numberOption(options, name, fallback) {
  const value = Number(options[name] ?? fallback);
  if (!Number.isFinite(value) || value <= 0) fail(`--${name} must be positive`);
  return String(value);
}

function launcher(options, name, binaryFallback = "codeagentcli") {
  const raw = options[name];
  if (raw === undefined) return [options[name.replace("launcher", "binary")] ?? binaryFallback];
  let value;
  try { value = JSON.parse(raw); } catch { fail(`--${name} must be a JSON string array`); }
  if (!Array.isArray(value) || value.length === 0 || value.some((item) => typeof item !== "string" || !item.trim())) {
    fail(`--${name} must be a non-empty JSON string array`);
  }
  return value;
}

function detectPython(options) {
  if (options.python) return options.python;
  if (process.env.PYTHON) return process.env.PYTHON;
  const local = process.platform === "win32"
    ? join(repoRoot, ".venv", "Scripts", "python.exe")
    : join(repoRoot, ".venv", "bin", "python");
  if (existsSync(local)) return local;
  return process.platform === "win32" ? "python" : "python3";
}

async function run(command, args, label) {
  console.log(`\n[${label}] ${command} ${args.map((item) => JSON.stringify(item)).join(" ")}`);
  if (dryRun) return;
  const child = spawn(command, args, { cwd: repoRoot, stdio: "inherit", shell: false });
  const forward = (signal) => child.kill(signal);
  process.once("SIGINT", forward);
  process.once("SIGTERM", forward);
  const code = await new Promise((resolveCode, reject) => {
    child.once("error", reject);
    child.once("exit", (exitCode, signal) => resolveCode(exitCode ?? (signal ? 1 : 0)));
  }).catch((error) => fail(`${label} could not start: ${error.message}`));
  process.removeListener("SIGINT", forward);
  process.removeListener("SIGTERM", forward);
  if (code !== 0) throw new Error(`${label} failed with exit code ${code}`);
}

function requirePath(path, label) {
  const absolute = resolve(path);
  if (!existsSync(absolute)) fail(`missing ${label}: ${absolute}`);
  return absolute;
}

function addPrompt(args, flag, value) {
  if (value) args.push(flag, requirePath(value, flag));
}

function selection(options, preset) {
  if (preset === "calibration") {
    if (!options["confirm-full-haystack"]) fail("calibration requires --confirm-full-haystack");
    const setPath = join(repoRoot, "evaluation", "calibration_sets", "codeagent_memory_web_small_10.json");
    const set = JSON.parse(readFileSync(setPath, "utf8"));
    return { domain: set.domain, tier: set.tier, questionIds: set.question_ids, fullHaystack: true };
  }
  if (preset === "small") {
    if (!options["confirm-full-run"]) fail("small preset requires --confirm-full-run");
    return { domain: options.domain ?? "web", tier: "small", allQuestions: true, fullHaystack: true };
  }
  const questionIds = options["question-id"] ?? (options["question-ids"] ? options["question-ids"].split(",") : ["05cce9b3"]);
  return {
    domain: options.domain ?? "web", tier: options.tier ?? "small", questionIds,
    allQuestions: Boolean(options["all-questions"]), fullHaystack: Boolean(options["full-haystack"]),
    haystackLimit: numberOption(options, "haystack-limit", 3),
  };
}

function commonEvalArgs(options, selected, mode, ingestLauncher, ingestPrompt) {
  const args = [
    join(repoRoot, "evaluation", "run_eval.py"), "--method", "codeagent_auto_memory",
    "--data-root", requirePath(options["data-root"], "data root"), "--domain", selected.domain,
    "--tier", selected.tier, "--codeagent-auto-memory-experiment-mode", mode,
    "--codeagent-auto-memory-runtime", options.runtime ?? "codeagent",
    "--codeagent-auto-memory-launcher-command-json", JSON.stringify(ingestLauncher),
    "--codeagent-auto-memory-ingest-launcher-command-json", JSON.stringify(ingestLauncher),
    "--codeagent-auto-memory-timeout-seconds", numberOption(options, "timeout-seconds", 1800),
    "--codeagent-auto-memory-ingest-max-turns", numberOption(options, "ingest-max-turns", 60),
    "--codeagent-auto-memory-query-max-turns", numberOption(options, "query-max-turns", 20),
    "--codeagent-auto-memory-ingest-max-attempts", numberOption(options, "ingest-max-attempts", 2),
    "--codeagent-auto-memory-query-max-attempts", numberOption(options, "query-max-attempts", 2),
  ];
  if (options.model) args.push("--codeagent-auto-memory-model", options.model);
  if (!selected.allQuestions) args.push("--question-ids", ...selected.questionIds);
  if (!selected.fullHaystack) args.push("--haystack-limit", selected.haystackLimit);
  addPrompt(args, "--codeagent-auto-memory-ingest-prompt-file", ingestPrompt);
  return args;
}

function ensureOutput(options) {
  if (!options["data-root"] || !options["output-root"]) fail("--data-root and --output-root are required");
  const output = resolve(options["output-root"]);
  if (existsSync(output) && !options.resume) fail(`output root exists; use --resume to continue: ${output}`);
  if (!dryRun) {
    const manifestPath = join(output, "runner_config.json");
    const ignored = new Set(["resume", "dry-run", "confirm-full-run", "confirm-full-haystack"]);
    const normalized = Object.fromEntries(Object.entries(options)
      .filter(([key]) => !ignored.has(key))
      .map(([key, value]) => [key, key === "data-root" || key === "output-root" ? resolve(value) : value])
      .sort(([left], [right]) => left.localeCompare(right)));
    if (options.resume) {
      if (!existsSync(manifestPath)) fail(`cannot resume without runner_config.json: ${output}`);
      const saved = JSON.parse(readFileSync(manifestPath, "utf8"));
      if (JSON.stringify(saved.config) !== JSON.stringify(normalized)) {
        fail("resume configuration differs from runner_config.json; use the original arguments or a new output root");
      }
    } else {
      mkdirSync(output, { recursive: true });
      writeFileSync(manifestPath, `${JSON.stringify({
        schema_version: 1, runner: "run_codeagent_memory_eval.mjs",
        node_version: process.version, platform: process.platform, config: normalized,
      }, null, 2)}\n`, "utf8");
    }
  }
  return output;
}

async function runAttribution(options) {
  const output = ensureOutput(options);
  const selected = selection(options, options.preset ?? "smoke");
  const python = detectPython(options);
  const writerA = launcher(options, "writer-a-launcher");
  const writerB = launcher(options, "writer-b-launcher");
  const recallA = launcher(options, "recall-a-launcher");
  const recallB = launcher(options, "recall-b-launcher");

  async function build(name, mode, writer, prompt) {
    const buildDir = join(output, name, "build");
    if (options.resume && existsSync(join(buildDir, "memory_state", "ingestion_manifest.json"))) {
      console.log(`[${name}] completed memory state found; skipping`); return;
    }
    const args = commonEvalArgs(options, selected, mode, writer, prompt);
    if (options.resume && existsSync(join(buildDir, "memory_workspace", "shared", "ingestion_manifest.json"))) {
      args.push("--codeagent-auto-memory-resume-build");
    }
    args.push("--output-dir", buildDir, "--save-memory", "--skip-evaluation");
    await run(python, args, `${name}:build`);
  }

  async function evaluate(cell, writerName, mode, writer, ingestPrompt, recall, queryPrompt, answerPrompt) {
    const evalDir = join(output, cell, "evaluate");
    if (options.resume && existsSync(join(evalDir, "per_question.jsonl"))) {
      console.log(`[${cell}] completed evaluation found; skipping`); return;
    }
    const args = commonEvalArgs(options, selected, mode, writer, ingestPrompt);
    args.push("--codeagent-auto-memory-query-launcher-command-json", JSON.stringify(recall));
    args.push("--codeagent-auto-memory-allow-query-override-on-load");
    addPrompt(args, "--codeagent-auto-memory-query-prompt-file", queryPrompt);
    addPrompt(args, "--codeagent-auto-memory-direct-answer-prompt-file", answerPrompt);
    args.push("--output-dir", evalDir, "--load-memory-dir", join(output, writerName, "build", "memory_state"));
    await run(python, args, `${cell}:evaluate`);
  }

  await build("writer_a", "baseline", writerA, options["writer-a-ingest-prompt"]);
  await build("writer_b", "candidate", writerB, options["writer-b-ingest-prompt"]);
  await evaluate("aa", "writer_a", "baseline", writerA, options["writer-a-ingest-prompt"], recallA, options["recall-a-query-prompt"], options["recall-a-answer-prompt"]);
  await evaluate("ab", "writer_a", "baseline", writerA, options["writer-a-ingest-prompt"], recallB, options["recall-b-query-prompt"], options["recall-b-answer-prompt"]);
  await evaluate("ba", "writer_b", "candidate", writerB, options["writer-b-ingest-prompt"], recallA, options["recall-a-query-prompt"], options["recall-a-answer-prompt"]);
  await evaluate("bb", "writer_b", "candidate", writerB, options["writer-b-ingest-prompt"], recallB, options["recall-b-query-prompt"], options["recall-b-answer-prompt"]);
  const reportDir = join(output, "attribution");
  if (!(options.resume && existsSync(join(reportDir, "report.html")))) {
    await run(python, [join(repoRoot, "evaluation", "compare_memory_attribution.py"),
      "--aa", join(output, "aa", "evaluate"), "--ab", join(output, "ab", "evaluate"),
      "--ba", join(output, "ba", "evaluate"), "--bb", join(output, "bb", "evaluate"),
      "--writer-a-state", join(output, "writer_a", "build", "memory_state"),
      "--writer-b-state", join(output, "writer_b", "build", "memory_state"),
      "--output-dir", reportDir], "attribution:report");
  }
  console.log(`\nHTML report: ${join(reportDir, "report.html")}`);
}

async function runRegression(options) {
  const output = ensureOutput(options);
  const selected = selection(options, options.preset ?? "smoke");
  const python = detectPython(options);
  const groups = [
    ["memory_off", "memory_off", launcher(options, "memory-off-launcher"), "memory-off"],
    ["baseline", "baseline", launcher(options, "baseline-launcher"), options["baseline-version-label"] ?? "baseline"],
    ["candidate", "candidate", launcher(options, "candidate-launcher"), options["candidate-version-label"] ?? "candidate"],
  ];
  for (const [name, mode, command, version] of groups) {
    const buildDir = join(output, name, "build");
    const evalDir = join(output, name, "evaluate");
    const ingestPrompt = mode === "candidate" ? options["candidate-ingest-prompt"] : options["baseline-ingest-prompt"];
    const answerPrompt = mode === "candidate" ? options["candidate-answer-prompt"] : options["baseline-answer-prompt"];
    const common = () => {
      const args = commonEvalArgs(options, selected, mode, command, ingestPrompt);
      args.push("--codeagent-auto-memory-version-label", version);
      addPrompt(args, "--codeagent-auto-memory-direct-answer-prompt-file", answerPrompt);
      return args;
    };
    if (!(options.resume && existsSync(join(buildDir, "memory_state", "ingestion_manifest.json")))) {
      const args = common();
      if (options.resume && existsSync(join(buildDir, "memory_workspace", "shared", "ingestion_manifest.json"))) args.push("--codeagent-auto-memory-resume-build");
      args.push("--output-dir", buildDir, "--save-memory", "--skip-evaluation");
      await run(python, args, `${name}:build`);
    }
    if (!(options.resume && existsSync(join(evalDir, "per_question.jsonl")))) {
      const args = common();
      args.push("--output-dir", evalDir, "--load-memory-dir", join(buildDir, "memory_state"));
      await run(python, args, `${name}:evaluate`);
    }
  }
  const reportDir = join(output, "comparison");
  if (!(options.resume && existsSync(join(reportDir, "report.md")))) {
    await run(python, [join(repoRoot, "evaluation", "compare_memory_regression.py"),
      "--memory-off", join(output, "memory_off", "evaluate"), "--baseline", join(output, "baseline", "evaluate"),
      "--candidate", join(output, "candidate", "evaluate"), "--output-dir", reportDir], "regression:report");
  }
  console.log(`\nRegression report: ${join(reportDir, "report.md")}`);
}

const options = parseArgs(process.argv.slice(2));
if (options.help || options._.length === 0) { usage(); process.exit(options.help ? 0 : 2); }
dryRun = Boolean(options["dry-run"]);
const command = options._[0];
try {
  if (command === "attribution") await runAttribution(options);
  else if (command === "regression") await runRegression(options);
  else fail(`unknown command: ${command}`);
} catch (error) {
  console.error(`\nerror: ${error.message}`);
  process.exit(1);
}
