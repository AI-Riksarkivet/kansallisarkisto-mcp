package main

import (
	"context"
	"dagger/kansallisarkisto-mcp/internal/dagger"
)

// Test runs the test suite with dev dependencies
func (m *KansallisarkistoMcp) Test(
	ctx context.Context,
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
	// Base image to use
	// +default="python:3.13-slim"
	baseImage string,
) (string, error) {
	if source == nil {
		source = dag.CurrentModule().Source()
	}

	container := dag.Container().
		From(baseImage).
		WithFile("/usr/local/bin/uv", dag.Container().From("ghcr.io/astral-sh/uv:latest").File("/uv")).
		WithFile("/usr/local/bin/uvx", dag.Container().From("ghcr.io/astral-sh/uv:latest").File("/uvx")).
		WithWorkdir("/app").
		WithDirectory("/app", source, dagger.ContainerWithDirectoryOpts{
			Include: []string{
				"pyproject.toml",
				"uv.lock",
				"packages/",
				"README.md",
			},
		}).
		WithExec([]string{"uv", "sync", "--frozen", "--no-cache", "--all-packages"})

	output, err := container.
		WithExec([]string{"uv", "run", "pytest", "--tb=short", "-q"}).
		Stdout(ctx)

	if err != nil {
		return "", err
	}

	return output, nil
}
