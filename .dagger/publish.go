package main

import (
	"context"
	"dagger/kansallisarkisto-mcp/internal/dagger"
	"fmt"
)

// testAndBuild runs tests and builds the container if tests pass
func (m *KansallisarkistoMcp) testAndBuild(ctx context.Context, source *dagger.Directory, operation string) (*dagger.Container, error) {
	_, err := m.Test(ctx, source, "python:3.13-slim")
	if err != nil {
		return nil, fmt.Errorf("tests failed, aborting %s: %w", operation, err)
	}

	container, err := m.Build(ctx, source)
	if err != nil {
		return nil, fmt.Errorf("build failed during %s: %w", operation, err)
	}

	return container, nil
}

// resolveTag resolves the final tag to use, with optional version validation
func (m *KansallisarkistoMcp) resolveTag(ctx context.Context, source *dagger.Directory, tag string, skipValidation bool) (string, error) {
	if tag == "" {
		version, err := m.getVersion(ctx, source)
		if err != nil {
			return "", err
		}
		return "v" + version, nil
	}

	if !skipValidation {
		if err := m.validateVersion(ctx, source, tag); err != nil {
			return "", err
		}
	}

	return tag, nil
}

// PublishDocker builds, tests, and publishes the container image to a registry
func (m *KansallisarkistoMcp) PublishDocker(
	ctx context.Context,
	// +default="riksarkivet/kansallisarkisto-mcp"
	imageRepository string,
	// Image tag (if empty, uses the version from packages/kansallisarkisto-mcp/pyproject.toml with "v" prefix)
	// +optional
	tag string,
	// +default="docker.io"
	registry string,
	// Docker username for authentication (use env: prefix for environment variables)
	dockerUsername *dagger.Secret,
	// Docker password from environment variable
	dockerPassword *dagger.Secret,
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
	// Skip version validation (not recommended for releases)
	// +optional
	skipValidation bool,
) (string, error) {
	resolvedTag, err := m.resolveTag(ctx, source, tag, skipValidation)
	if err != nil {
		return "", err
	}

	container, err := m.testAndBuild(ctx, source, "Docker publish")
	if err != nil {
		return "", err
	}

	imageRef := registry + "/" + imageRepository + ":" + resolvedTag

	if dockerPassword != nil && dockerUsername != nil {
		username, err := dockerUsername.Plaintext(ctx)
		if err != nil {
			return "", fmt.Errorf("failed to read docker username: %w", err)
		}
		return container.
			WithRegistryAuth(registry, username, dockerPassword).
			Publish(ctx, imageRef)
	}

	return container.Publish(ctx, imageRef)
}
