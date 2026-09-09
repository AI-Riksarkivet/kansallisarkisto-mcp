package main

import (
	"context"
	"dagger/kansallisarkisto-mcp/internal/dagger"
)

// Build creates the production container image from .docker/kansallisarkisto-mcp.dockerfile
func (m *KansallisarkistoMcp) Build(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	source *dagger.Directory,
) (*dagger.Container, error) {
	container := source.DockerBuild(dagger.DirectoryDockerBuildOpts{
		Dockerfile: ".docker/kansallisarkisto-mcp.dockerfile",
	})

	return container, nil
}
