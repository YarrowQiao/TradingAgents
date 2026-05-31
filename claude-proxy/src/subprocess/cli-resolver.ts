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
import { existsSync } from "node:fs";
import { join } from "node:path";

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
