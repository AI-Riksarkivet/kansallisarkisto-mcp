.PHONY: install harvest verify-data ingest-df scan sbom serve serve-http inspect format lint typecheck check test test-mcp ci clean

# Install dependencies (all workspace packages + dev group)
install:
	uv sync --all-packages

# Re-download the corpora from sisaltohaku.demo.kansallisarkisto.fi into .data/
# (df ~3s; voudintilit ~1min; tuomiokirjat ~1.5h and 6.3 GB — pass --index to pick one)
harvest:
	uv run python scripts/harvest.py --index df --sleep 0.2

# Check a harvested corpus reads back cleanly with unique objectIDs
verify-data:
	uv run python scripts/harvest.py --verify --index df

# Build the df LanceDB table from the harvested export in .data/
ingest-df:
	uv run python scripts/ingest_df.py

# Run MCP server (stdio transport)
serve:
	uv run kansallisarkisto-mcp

# Run MCP server (streamable HTTP transport on :8000)
serve-http:
	KA_MCP_TRANSPORT=http uv run kansallisarkisto-mcp

# Open MCP Inspector
inspect:
	npx @modelcontextprotocol/inspector uv run kansallisarkisto-mcp

# Format code
format:
	uv run ruff format .

# Lint and auto-fix
lint:
	uv run ruff check --fix .

# Type check
typecheck:
	uvx ty check

# Local code quality checks (format + lint + typecheck)
check: format lint typecheck

# Run tests
test:
	uv run pytest

# Scan the production image with Trivy (fixable CRITICAL/HIGH gate, as CI runs it)
scan:
	dagger call scan

# Write both SBOM formats next to the repo
sbom:
	dagger call generate-sbom-spdx export --path ./sbom.spdx.json
	dagger call generate-sbom-cyclone-dx export --path ./sbom.cyclonedx.json

# End-to-end MCP smoke test: production image + the test fixture ingested into a
# mounted LanceDB table (offline)
test-mcp:
	dagger call test-mcp

# Run full CI pipeline via Dagger (same as GitHub Actions)
ci:
	dagger call checks
	dagger call test
	dagger call test-mcp

# Run the image on the Dagger engine with the test fixture already ingested,
# exposed on the host for manual poking
serve-image:
	dagger call serve-up --port 8000 up --ports 8000:8000

# Clean build artifacts
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	rm -rf dist/ build/ *.egg-info
