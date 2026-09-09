package main

import (
	"context"
	"dagger/kansallisarkisto-mcp/internal/dagger"
	"fmt"
)

// healthCheckCmd probes the server. It has a /health route, so anything but a
// 200 is a genuine failure.
func healthCheckCmd(host string, port int) []string {
	return []string{"sh", "-c", fmt.Sprintf(
		`code=$(curl -s -o /dev/null -w '%%{http_code}' http://%s:%d/health); echo "HTTP $code"; [ "$code" = "200" ]`,
		host, port,
	)}
}

// fixtureData ingests the 16-charter test fixture into a LanceDB database and
// returns it as a directory, so the image can be exercised against a real table
// without shipping (or harvesting) the corpus.
func (m *KansallisarkistoMcp) fixtureData(ctx context.Context, source *dagger.Directory) (*dagger.Directory, error) {
	container, err := m.buildWithUv(ctx, source)
	if err != nil {
		return nil, err
	}

	return container.
		WithExec([]string{
			"uv", "run", "python", "scripts/ingest_df.py",
			"--jsonl", "packages/kansallisarkisto-lib/tests/fixtures/df_sample.jsonl",
			"--output", "/tmp/lancedb",
		}).
		Directory("/tmp/lancedb"), nil
}

// Serve starts the kansallisarkisto-mcp server as a service (streamable HTTP transport)
func (m *KansallisarkistoMcp) Serve(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
	// Port to expose the service on
	// +default=8000
	port int,
	// LanceDB directory to mount at /data; without it the server boots and the
	// tools return a clear missing-table error
	// +optional
	data *dagger.Directory,
) (*dagger.Service, error) {
	container, err := m.Build(ctx, source)
	if err != nil {
		return nil, err
	}

	container = container.
		WithEnvVariable("KA_MCP_TRANSPORT", "http").
		WithEnvVariable("KA_LANCEDB_URI", "/data").
		WithEnvVariable("HOST", "0.0.0.0").
		WithEnvVariable("PORT", fmt.Sprintf("%d", port))

	if data != nil {
		// Owner matters: lance writes its data and index files mode 0600, so a
		// directory copied in as root is unreadable by the USER 1000 runtime —
		// and lance surfaces that EACCES as a misleading "Not found: ...".
		container = container.WithDirectory("/data", data, dagger.ContainerWithDirectoryOpts{Owner: "1000:1000"})
	}

	return container.
		WithExposedPort(port).
		AsService(dagger.ContainerAsServiceOpts{
			Args: []string{"/app/.venv/bin/kansallisarkisto-mcp"},
		}), nil
}

// TestServer builds and starts the server, then runs a health check
func (m *KansallisarkistoMcp) TestServer(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
	// Port to expose the service on
	// +default=8000
	port int,
) (string, error) {
	service, err := m.Serve(ctx, source, port, nil)
	if err != nil {
		return "", fmt.Errorf("failed to start service: %w", err)
	}

	output, err := dag.Container().
		From("curlimages/curl:latest").
		WithServiceBinding("kansallisarkisto-mcp", service).
		WithExec(healthCheckCmd("kansallisarkisto-mcp", port)).
		Stdout(ctx)
	if err != nil {
		return "", fmt.Errorf("health check failed: %w", err)
	}

	return fmt.Sprintf("✅ Server responded on port %d\n\n%s", port, output), nil
}

// ServeUp builds and exposes the server on the host for manual testing, with the
// test fixture ingested so the tools have something to search
func (m *KansallisarkistoMcp) ServeUp(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
	// Port to expose on host
	// +default=8000
	port int,
) (*dagger.Service, error) {
	data, err := m.fixtureData(ctx, source)
	if err != nil {
		return nil, err
	}
	return m.Serve(ctx, source, port, data)
}

// ServePublished runs a published Docker image from a registry
func (m *KansallisarkistoMcp) ServePublished(
	ctx context.Context,
	// Docker image reference
	// +default="riksarkivet/kansallisarkisto-mcp:latest"
	imageRef string,
	// Port to expose
	// +default=8000
	port int,
) (*dagger.Service, error) {
	return dag.Container().
		From(imageRef).
		WithEnvVariable("KA_MCP_TRANSPORT", "http").
		WithEnvVariable("KA_LANCEDB_URI", "/data").
		WithEnvVariable("HOST", "0.0.0.0").
		WithEnvVariable("PORT", fmt.Sprintf("%d", port)).
		WithExposedPort(port).
		AsService(dagger.ContainerAsServiceOpts{
			Args: []string{"/app/.venv/bin/kansallisarkisto-mcp"},
		}), nil
}

// TestPublished tests a published Docker image from a registry
func (m *KansallisarkistoMcp) TestPublished(
	ctx context.Context,
	// Docker image reference
	// +default="riksarkivet/kansallisarkisto-mcp:latest"
	imageRef string,
	// Port to test
	// +default=8000
	port int,
) (string, error) {
	service, err := m.ServePublished(ctx, imageRef, port)
	if err != nil {
		return "", fmt.Errorf("failed to start published image: %w", err)
	}

	output, err := dag.Container().
		From("curlimages/curl:latest").
		WithServiceBinding("kansallisarkisto-mcp", service).
		WithExec(healthCheckCmd("kansallisarkisto-mcp", port)).
		Stdout(ctx)
	if err != nil {
		return "", fmt.Errorf("health check failed: %w", err)
	}

	return fmt.Sprintf("✅ Published image %s responded\n\n%s", imageRef, output), nil
}
