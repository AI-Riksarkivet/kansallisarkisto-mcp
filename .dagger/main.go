// Kansallisarkisto-MCP Dagger CI/CD Pipeline
package main

import (
	"context"
	"dagger/kansallisarkisto-mcp/internal/dagger"
)

// KansallisarkistoMcp provides CI/CD pipeline functions for the kansallisarkisto-mcp project
type KansallisarkistoMcp struct{}

// Default configuration constants. Dagger's +default annotations can't reference Go
// constants (they require inline literals), so these aren't consumed by the module itself —
// they document the canonical registry/repo that the inlined +default literals elsewhere in
// this module must be kept in sync with.
const (
	DefaultRegistry  = "docker.io"
	DefaultImageRepo = "riksarkivet/kansallisarkisto-mcp"
)

// withUv adds uv to a container (for development/CI tasks only)
func (m *KansallisarkistoMcp) withUv(container *dagger.Container) *dagger.Container {
	uvBinary := dag.Container().
		From("ghcr.io/astral-sh/uv:latest").
		File("/uv")

	uvxBinary := dag.Container().
		From("ghcr.io/astral-sh/uv:latest").
		File("/uvx")

	return container.
		WithFile("/usr/local/bin/uv", uvBinary).
		WithFile("/usr/local/bin/uvx", uvxBinary)
}

// buildWithUv creates a development container with uv tooling and all workspace packages
func (m *KansallisarkistoMcp) buildWithUv(ctx context.Context, source *dagger.Directory) (*dagger.Container, error) {
	container := dag.Container().
		From("python:3.14-slim").
		WithDirectory("/app", source).
		WithWorkdir("/app")

	container = m.withUv(container)

	container = container.WithExec([]string{"uv", "sync", "--frozen", "--no-cache", "--all-packages"})

	return container, nil
}
