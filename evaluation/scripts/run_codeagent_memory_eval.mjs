#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
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
    "all-questions", "full-haystack", "confirm-full-run", "confirm-full-haystack", "memory-off", "resume", "dry-run", "help",
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
  node evaluation/scripts/run_codeagent_memory_eval.mjs [single] --preset smoke [options]
  node evaluation/scripts/run_codeagent_memory_eval.mjs [single] --preset small [options]

Required:
  --data-root PATH                 Prepared LongMemEval-V2 data root
  --output-root PATH               Run archive root

Default single-run launcher:
  --launcher '["/opt/codeagent/codeagentcli"]'
  --cli-repo PATH                  CLI git repository when it cannot be inferred from launcher
  --commit-hash SHA                Explicit CLI commit when it cannot be auto-detected
  --ingestion-strategy NAME        trajectory_file (default) or historical_session
  --memory-off                     Run this package once with persistent memory disabled

Single runs are retained under <output-root>/<UTC timestamp>_<commit hash>.
Use --run-dir with --resume to continue one exact retained run.
Run the before-change and after-change packages separately with --launcher.
Every completed run writes evaluation_result.json and a multi-result report.html.

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

function capture(command, args, cwd = repoRoot) {
  const result = spawnSync(command, args, {
    cwd, encoding: "utf8", shell: false, timeout: 10000,
  });
  if (result.error || result.status !== 0) return null;
  return String(result.stdout || result.stderr || "").trim() || null;
}

function gitIdentity(repoPath) {
  const absolute = resolve(repoPath);
  const hash = capture("git", ["-C", absolute, "rev-parse", "HEAD"]);
  if (!hash || !/^[0-9a-f]{40}$/i.test(hash)) return null;
  const topLevel = capture("git", ["-C", absolute, "rev-parse", "--show-toplevel"]);
  const status = capture("git", ["-C", absolute, "status", "--porcelain"]);
  return { commitHash: hash.toLowerCase(), repo: topLevel ? resolve(topLevel) : absolute, dirty: Boolean(status) };
}

function inferCliGitIdentity(command) {
  for (const item of command) {
    const candidate = resolve(item);
    if (!existsSync(candidate)) continue;
    const identity = gitIdentity(candidate);
    if (identity) return identity;
    const parentIdentity = gitIdentity(dirname(candidate));
    if (parentIdentity) return parentIdentity;
  }
  return null;
}

function resolveCliIdentity(options, command) {
  const explicit = options["commit-hash"];
  if (explicit && !/^[0-9a-f]{7,40}$/i.test(explicit)) {
    fail("--commit-hash must contain 7 to 40 hexadecimal characters");
  }
  const git = options["cli-repo"] ? gitIdentity(requirePath(options["cli-repo"], "CLI repository")) : inferCliGitIdentity(command);
  if (options["cli-repo"] && !git) fail(`not a git repository: ${resolve(options["cli-repo"])}`);
  if (explicit) {
    if (git && !git.commitHash.startsWith(explicit.toLowerCase())) {
      fail(`--commit-hash ${explicit} does not match CLI repository HEAD ${git.commitHash}`);
    }
    return { commitHash: git?.commitHash ?? explicit.toLowerCase(), repo: git?.repo ?? null, dirty: git?.dirty ?? null, source: "explicit" };
  }
  if (git) return { ...git, source: "git" };
  const version = capture(command[0], [...command.slice(1), "--version"]);
  const versionHash = version?.match(/\b[0-9a-f]{7,40}\b/i)?.[0];
  if (versionHash) return { commitHash: versionHash.toLowerCase(), repo: null, dirty: null, source: "version", version };
  fail("could not determine the specified CLI commit; pass --cli-repo PATH or --commit-hash SHA");
}

function utcRunTimestamp(date) {
  return date.toISOString().replaceAll("-", "").replaceAll(":", "").replace(".", "");
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
  const runtime = options.runtime ?? "codeagent";
  if (!new Set(["codeagent", "free_code"]).has(runtime)) fail("--runtime must be codeagent or free_code");
  const ingestionStrategy = options["ingestion-strategy"] ?? "trajectory_file";
  if (!new Set(["trajectory_file", "historical_session"]).has(ingestionStrategy)) {
    fail("--ingestion-strategy must be trajectory_file or historical_session");
  }
  if (ingestionStrategy === "historical_session" && runtime !== "free_code") {
    fail("--ingestion-strategy historical_session requires --runtime free_code");
  }
  const args = [
    join(repoRoot, "evaluation", "run_eval.py"), "--method", "codeagent_auto_memory",
    "--data-root", requirePath(options["data-root"], "data root"), "--domain", selected.domain,
    "--tier", selected.tier, "--codeagent-auto-memory-experiment-mode", mode,
    "--codeagent-auto-memory-runtime", runtime,
    "--codeagent-auto-memory-launcher-command-json", JSON.stringify(ingestLauncher),
    "--codeagent-auto-memory-ingest-launcher-command-json", JSON.stringify(ingestLauncher),
    "--codeagent-auto-memory-timeout-seconds", numberOption(options, "timeout-seconds", 1800),
    "--codeagent-auto-memory-ingest-max-turns", numberOption(options, "ingest-max-turns", 60),
    "--codeagent-auto-memory-query-max-turns", numberOption(options, "query-max-turns", 20),
    "--codeagent-auto-memory-ingest-max-attempts", numberOption(options, "ingest-max-attempts", 2),
    "--codeagent-auto-memory-ingestion-strategy", ingestionStrategy,
    "--codeagent-auto-memory-query-max-attempts", numberOption(options, "query-max-attempts", 2),
  ];
  if (options.model) args.push("--codeagent-auto-memory-model", options.model);
  if (!selected.allQuestions) args.push("--question-ids", ...selected.questionIds);
  if (!selected.fullHaystack) args.push("--haystack-limit", selected.haystackLimit);
  addPrompt(args, "--codeagent-auto-memory-ingest-prompt-file", ingestPrompt);
  return args;
}

function ensureOutput(options, outputPath = options["output-root"], identity = null) {
  if (!options["data-root"] || !outputPath) fail("--data-root and --output-root are required");
  const output = resolve(outputPath);
  if (existsSync(output) && !options.resume) fail(`output root exists; use --resume to continue: ${output}`);
  if (!dryRun) {
    const manifestPath = join(output, "runner_config.json");
    const ignored = new Set(["resume", "run-dir", "dry-run", "confirm-full-run", "confirm-full-haystack"]);
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
        ...(identity ? { run_identity: identity } : {}),
      }, null, 2)}\n`, "utf8");
    }
  }
  return output;
}

async function runSingle(options) {
  if (!options["output-root"]) fail("--output-root is required");
  const command = launcher(options, "launcher");
  const identity = resolveCliIdentity(options, command);
  const startedAt = new Date();
  const timestampUtc = startedAt.toISOString();
  const shortHash = identity.commitHash.slice(0, 12);
  const mode = options["memory-off"] ? "memory_off" : "single";
  const generatedName = `${utcRunTimestamp(startedAt)}_${shortHash}${identity.dirty ? "_dirty" : ""}${mode === "memory_off" ? "_memory_off" : ""}`;
  if (options.resume && !options["run-dir"]) fail("single-run --resume requires --run-dir PATH");
  const outputPath = options["run-dir"] ?? join(resolve(options["output-root"]), generatedName);
  const runIdentity = {
    timestamp_utc: timestampUtc,
    commit_hash: identity.commitHash,
    short_commit_hash: shortHash,
    commit_source: identity.source,
    cli_repo: identity.repo,
    git_dirty: identity.dirty,
    launcher_command: command,
    experiment_mode: mode,
    ...(identity.version ? { detected_version: identity.version } : {}),
  };
  const output = ensureOutput(options, outputPath, runIdentity);
  const selected = selection(options, options.preset ?? "smoke");
  const python = detectPython(options);
  const version = options["version-label"] ?? identity.commitHash;
  const common = () => {
    const args = commonEvalArgs(options, selected, mode, command, options["ingest-prompt"]);
    args.push("--codeagent-auto-memory-version-label", version);
    addPrompt(args, "--codeagent-auto-memory-query-prompt-file", options["query-prompt"]);
    addPrompt(args, "--codeagent-auto-memory-direct-answer-prompt-file", options["answer-prompt"]);
    return args;
  };
  const buildDir = join(output, "build");
  const evalDir = join(output, "evaluate");
  if (!(options.resume && existsSync(join(buildDir, "memory_state", "ingestion_manifest.json")))) {
    const args = common();
    if (options.resume && existsSync(join(buildDir, "memory_workspace", "shared", "ingestion_manifest.json"))) {
      args.push("--codeagent-auto-memory-resume-build");
    }
    args.push("--output-dir", buildDir, "--save-memory", "--skip-evaluation");
    await run(python, args, `${mode}:build`);
  }
  if (!(options.resume && existsSync(join(evalDir, "per_question.jsonl")))) {
    const args = common();
    args.push("--output-dir", evalDir, "--load-memory-dir", join(buildDir, "memory_state"));
    await run(python, args, `${mode}:evaluate`);
  }
  await run(python, [
    join(repoRoot, "evaluation", "build_single_run_result.py"),
    "--run-dir", output,
  ], `${mode}:result`);
  console.log(`\nRun directory: ${output}`);
  console.log(`Result JSON: ${join(output, "evaluation_result.json")}`);
  console.log(`Comparison HTML: ${join(output, "report.html")}`);
}

const options = parseArgs(process.argv.slice(2));
if (options.help) { usage(); process.exit(0); }
dryRun = Boolean(options["dry-run"]);
const command = options._[0] ?? "single";
try {
  if (command === "single") await runSingle(options);
  else fail(`unknown command: ${command}`);
} catch (error) {
  console.error(`\nerror: ${error.message}`);
  process.exit(1);
}
