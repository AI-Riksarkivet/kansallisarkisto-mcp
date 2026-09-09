// Kansallisarkisto-MCP Dagger CI/CD Pipeline
package main

import (
	"context"
	"dagger/kansallisarkisto-mcp/internal/dagger"
	"fmt"
	"strings"
)

// KansallisarkistoMcp provides CI/CD pipeline functions for the kansallisarkisto-mcp project
type KansallisarkistoMcp struct{}

// Default configuration constants. Dagger's +default annotations can't reference Go
// constants (they require inline literals), so these aren't consumed by the module itself —
// they document the canonical registry/repo that those inlined +default literals (see
// publish.go) must be kept in sync with.
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
		From("python:3.13-slim").
		WithDirectory("/app", source).
		WithWorkdir("/app")

	container = m.withUv(container)

	container = container.WithExec([]string{"uv", "sync", "--frozen", "--no-cache", "--all-packages"})

	return container, nil
}

// getVersion retrieves the version of the kansallisarkisto-mcp package. The workspace root
// pyproject.toml has no [project] section, so the version lives in
// packages/kansallisarkisto-mcp/pyproject.toml and uv must run from that directory.
func (m *KansallisarkistoMcp) getVersion(ctx context.Context, source *dagger.Directory) (string, error) {
	container := dag.Container().
		From("python:3.13-slim").
		WithDirectory("/app", source).
		WithWorkdir("/app/packages/kansallisarkisto-mcp")

	container = m.withUv(container)

	version, err := container.
		WithExec([]string{"uv", "version", "--short"}).
		Stdout(ctx)

	if err != nil {
		return "", err
	}

	return strings.TrimSpace(version), nil
}

// validateVersion checks if the provided tag matches the packaged version
func (m *KansallisarkistoMcp) validateVersion(ctx context.Context, source *dagger.Directory, tag string) error {
	projectVersion, err := m.getVersion(ctx, source)
	if err != nil {
		return fmt.Errorf("failed to get version from packages/kansallisarkisto-mcp/pyproject.toml: %w", err)
	}

	normalizeVersion := func(v string) string {
		return strings.TrimPrefix(strings.TrimSpace(v), "v")
	}

	normalizedProject := normalizeVersion(projectVersion)
	normalizedTag := normalizeVersion(tag)

	if normalizedProject != normalizedTag {
		return fmt.Errorf(
			"version mismatch: packages/kansallisarkisto-mcp/pyproject.toml has version 'v%s' but release tag is '%s'",
			projectVersion,
			tag,
		)
	}

	return nil
}
