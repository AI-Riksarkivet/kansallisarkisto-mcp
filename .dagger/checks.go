package main

import (
	"context"
	"dagger/kansallisarkisto-mcp/internal/dagger"
	"fmt"
)

const pipAuditRequirementsFile = "pip-audit-requirements.txt"

var (
	ruffFormatCmd      = []string{"uvx", "ruff", "format", "."}
	ruffFormatCheckCmd = []string{"uvx", "ruff", "format", "--check", "."}
	ruffCheckFixCmd    = []string{"uvx", "ruff", "check", "--fix", "."}
	ruffCheckCmd       = []string{"uvx", "ruff", "check", "."}
	tyCheckCmd         = []string{"uvx", "ty", "check"}

	// pip-audit can only look up third-party packages against PyPI's advisory data, so the
	// two local workspace packages (ra-mcp-kansallisarkisto-lib, ra-mcp-kansallisarkisto-mcp) — which are never
	// published and always installed editable by `uv sync` — must be excluded from what it
	// audits rather than passed to it. `uv export --no-emit-workspace` produces exactly the
	// resolved, pinned third-party dependency set (the same one `uv sync --all-packages`
	// installed) with the workspace members left out, so pip-audit can run with `--strict`
	// against real dependencies only, instead of an ephemeral, unrelated pip-audit-only venv.
	pipAuditExportCmd = []string{
		"uv", "export", "--no-emit-workspace", "--format", "requirements-txt",
		"-o", pipAuditRequirementsFile,
	}
	pipAuditCmd = []string{
		"uv", "run", "--with", "pip-audit", "pip-audit", "--strict", "--desc",
		"-r", pipAuditRequirementsFile,
	}
)

// RuffFormat formats code using ruff (modifies files)
func (m *KansallisarkistoMcp) RuffFormat(
	ctx context.Context,
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
) (*dagger.Directory, error) {
	container, err := m.buildWithUv(ctx, source)
	if err != nil {
		return nil, err
	}

	formattedContainer := container.WithExec(ruffFormatCmd)

	return formattedContainer.Directory("/app"), nil
}

// RuffCheck fixes linting issues using ruff (modifies files)
func (m *KansallisarkistoMcp) RuffCheck(
	ctx context.Context,
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
) (*dagger.Directory, error) {
	container, err := m.buildWithUv(ctx, source)
	if err != nil {
		return nil, err
	}

	fixedContainer := container.WithExec(ruffCheckFixCmd)

	return fixedContainer.Directory("/app"), nil
}

// TypeCheck runs type checking with ty (check only, no modifications)
func (m *KansallisarkistoMcp) TypeCheck(
	ctx context.Context,
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
	// Ignore errors and return result anyway
	// +optional
	ignoreError bool,
) (string, error) {
	container, err := m.buildWithUv(ctx, source)
	if err != nil {
		return "", err
	}

	out, err := container.
		WithExec(tyCheckCmd).
		Stdout(ctx)

	if err != nil && !ignoreError {
		return "", fmt.Errorf("type check failed: %w", err)
	}
	return out, nil
}

// Checks runs all code quality checks: first fixes (format + lint), then verifies all pass
func (m *KansallisarkistoMcp) Checks(
	ctx context.Context,
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
) (string, error) {
	container, err := m.buildWithUv(ctx, source)
	if err != nil {
		return "", err
	}

	// Step 1: Apply formatting
	container = container.WithExec(ruffFormatCmd)

	// Step 2: Fix linting issues
	container = container.WithExec(ruffCheckFixCmd)

	// Step 3: Verify everything passes (format check, lint check, type check)
	_, err = container.
		WithExec(ruffFormatCheckCmd).
		WithExec(ruffCheckCmd).
		WithExec(tyCheckCmd).
		Sync(ctx)

	if err != nil {
		return "", fmt.Errorf("checks failed: %w", err)
	}

	// Step 4: Audit dependencies for known vulnerabilities
	_, err = container.
		WithExec(pipAuditExportCmd).
		WithExec(pipAuditCmd).
		Sync(ctx)

	if err != nil {
		return "", fmt.Errorf("pip-audit failed: %w", err)
	}

	return "All checks passed ✅ (after auto-formatting and auto-fixing)", nil
}
