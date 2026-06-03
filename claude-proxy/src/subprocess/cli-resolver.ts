/**
 * Resolves the absolute path to the Claude Code CLI executable.
 *
 * On Windows, `spawn("claude", ...)` cannot find `claude.cmd` (the npm-global
 * shim) because Node refuses to execute .cmd/.bat files without `shell: true`,
 * and piping stdin into a shell-wrapped process is unreliable. The npm-installed
 * Claude Code on Windows ships a real native `claude.exe`, so we resolve it
 * directly and spawn that.
 *
 * Override with CLAUDE_PROXY_CLI_PATH if the auto-resolver guesses wrong.
 */
import { existsSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

let cached: string | null = null;

export function resolveClaudeCommand(): string {
  if (cached) return cached;

  const override = process.env.CLAUDE_PROXY_CLI_PATH;
  if (override && existsSync(override)) {
    cached = override;
    return cached;
  }

  if (process.platform !== "win32") {
    cached = "claude";
    return cached;
  }

  const candidates: string[] = [];
  if (process.env.APPDATA) {
    candidates.push(
      join(
        process.env.APPDATA,
        "npm",
        "node_modules",
        "@anthropic-ai",
        "claude-code",
        "bin",
        "claude.exe",
      ),
    );
  }
  if (process.env.ProgramFiles) {
    candidates.push(
      join(
        process.env.ProgramFiles,
        "nodejs",
        "node_modules",
        "@anthropic-ai",
        "claude-code",
        "bin",
        "claude.exe",
      ),
    );
  }

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      cached = candidate;
      return cached;
    }
  }

  cached = "claude";
  return cached;
}

let cachedNeutralCwd: string | null = null;

/**
 * A neutral, empty working directory for spawned `claude` subprocesses.
 *
 * Without this the subprocess inherits the proxy's own `process.cwd()` — i.e.
 * the claude-proxy project directory. Claude Code then auto-loads that dir's
 * `CLAUDE.md` and `.claude/settings*`, so the model thinks it is "working in
 * the claude-proxy project" and blends those software-engineering instructions
 * into whatever the API caller actually requested (e.g. a stock-analyst
 * persona). The result is the "conflicting system messages" confusion where
 * the model stops and asks for clarification instead of answering.
 *
 * An empty temp dir has no CLAUDE.md, no `.claude/`, and is not a git repo, so
 * no project context leaks in. Created once and reused for the process
 * lifetime. Override with CLAUDE_PROXY_CWD if a specific dir is needed.
 */
export function neutralCwd(): string {
  const override = process.env.CLAUDE_PROXY_CWD;
  if (override) return override;
  if (cachedNeutralCwd) return cachedNeutralCwd;
  cachedNeutralCwd = mkdtempSync(join(tmpdir(), "claude-proxy-cwd-"));
  return cachedNeutralCwd;
}
