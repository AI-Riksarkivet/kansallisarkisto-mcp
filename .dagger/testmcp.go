package main

import (
	"context"
	"dagger/kansallisarkisto-mcp/internal/dagger"
	"fmt"
)

// TestMcp runs the end-to-end MCP smoke test: the production image serving real
// LanceDB tables built from the test fixtures (18 df charters, 12 voudintilit
// pages), with a real fastmcp client (scripts/mcp_smoke.py) listing and calling
// every tool.
//
// It is the only place the index configuration is actually verified end to end:
// Swedish stemming and accent folding are index-time settings, so a wrong FTS
// config is invisible to anything that searches only exact forms.
func (m *KansallisarkistoMcp) TestMcp(
	ctx context.Context,
	// Source directory containing scripts/, fixtures and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
) (string, error) {
	data, err := m.fixtureData(ctx, source)
	if err != nil {
		return "", fmt.Errorf("failed to build the fixture table: %w", err)
	}

	server, err := m.Serve(ctx, source, 8000, data)
	if err != nil {
		return "", fmt.Errorf("build failed before MCP smoke test: %w", err)
	}

	// Smoke client: the dev container already has fastmcp via the workspace sync.
	client, err := m.buildWithUv(ctx, source)
	if err != nil {
		return "", fmt.Errorf("failed to build smoke-test client: %w", err)
	}

	output, err := client.
		WithServiceBinding("kansallisarkisto-mcp", server).
		WithEnvVariable("MCP_URL", "http://kansallisarkisto-mcp:8000/mcp").
		WithExec([]string{"uv", "run", "python", "scripts/mcp_smoke.py"}).
		Stdout(ctx)
	if err != nil {
		return "", fmt.Errorf("MCP smoke test failed: %w", err)
	}

	return output, nil
}
