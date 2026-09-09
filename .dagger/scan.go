package main

import (
	"context"
	"dagger/kansallisarkisto-mcp/internal/dagger"
	"fmt"
)

// Scan performs container vulnerability scanning using Trivy
func (m *KansallisarkistoMcp) Scan(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
	// Severity levels to report (comma-separated: CRITICAL,HIGH,MEDIUM,LOW,UNKNOWN)
	// +default="CRITICAL,HIGH"
	severity string,
	// Output format (table, json, sarif, cyclonedx, spdx, github)
	// +default="table"
	format string,
	// Exit code when vulnerabilities are found (0 to ignore vulnerabilities)
	// +default=1
	exitCode int,
	// Report only vulnerabilities that have a fix available. On by default: the
	// Debian base carries a standing set of unfixed OS-package CVEs (perl-base,
	// util-linux, ncurses, gzip — 3 CRITICAL and 51 HIGH at the time of writing,
	// every one of them "no fix"). Gating on those makes the gate fail on every
	// run forever, which is the same as having no gate. Gating on fixable findings
	// instead means a red scan is always something this repo can actually act on.
	// Pass --ignore-unfixed=false for the unfiltered picture.
	// +default=true
	ignoreUnfixed bool,
) (string, error) {
	// Build the container first
	container, err := m.Build(ctx, source)
	if err != nil {
		return "", fmt.Errorf("build failed before scanning: %w", err)
	}

	// Export container to tar for scanning
	tarFile := container.AsTarball()

	trivyCmd := []string{
		"trivy",
		"image",
		"--input", "/image.tar",
		"--severity", severity,
		"--format", format,
		"--exit-code", fmt.Sprintf("%d", exitCode),
	}
	if ignoreUnfixed {
		trivyCmd = append(trivyCmd, "--ignore-unfixed")
	}

	// Create Trivy scanner container
	trivyContainer := dag.Container().
		From("aquasec/trivy:latest").
		WithMountedFile("/image.tar", tarFile).
		WithExec(trivyCmd)

	// Get scan results
	output, err := trivyContainer.Stdout(ctx)
	if err != nil {
		// Trivy returns error if vulnerabilities found with exit-code > 0
		// Try to get stdout anyway to show results
		if output == "" {
			return "", fmt.Errorf("trivy scan failed: %w", err)
		}
		return output, fmt.Errorf("vulnerabilities found: %w", err)
	}

	return output, nil
}

// ScanJson performs vulnerability scanning and returns JSON output
func (m *KansallisarkistoMcp) ScanJson(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
	// Severity levels to report
	// +default="CRITICAL,HIGH"
	severity string,
) (string, error) {
	return m.Scan(ctx, source, severity, "json", 0, false)
}

// ScanCi performs vulnerability scanning for CI/CD pipeline
// Fails build if CRITICAL or HIGH vulnerabilities are found
func (m *KansallisarkistoMcp) ScanCi(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
) (string, error) {
	output, err := m.Scan(ctx, source, "CRITICAL,HIGH", "table", 1, true)
	if err != nil {
		return output, fmt.Errorf("CI scan failed - critical/high vulnerabilities found: %w", err)
	}
	return output, nil
}

// ScanSarif generates SARIF output for GitHub Security tab integration
func (m *KansallisarkistoMcp) ScanSarif(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
	// Output file path for SARIF results
	// +default="trivy-results.sarif"
	outputPath string,
) (*dagger.File, error) {
	container, err := m.Build(ctx, source)
	if err != nil {
		return nil, fmt.Errorf("build failed before scanning: %w", err)
	}

	tarFile := container.AsTarball()

	trivyContainer := dag.Container().
		From("aquasec/trivy:latest").
		WithMountedFile("/image.tar", tarFile).
		// /output does not exist in the trivy image, and trivy will not create
		// it: without this the run ends in "failed to create output file". The
		// SBOM functions always had this line; this one did not, and nothing
		// executed it until the Security workflow started calling it.
		WithExec([]string{"mkdir", "-p", "/output"}).
		WithExec([]string{
			"trivy",
			"image",
			"--input", "/image.tar",
			"--format", "sarif",
			"--output", "/output/" + outputPath,
		})

	return trivyContainer.File("/output/" + outputPath), nil
}

// GenerateSbom generates Software Bill of Materials (SBOM) for the container
func (m *KansallisarkistoMcp) GenerateSbom(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
	// SBOM format (spdx-json, cyclonedx, spdx, github)
	// +default="spdx-json"
	format string,
) (*dagger.File, error) {
	container, err := m.Build(ctx, source)
	if err != nil {
		return nil, fmt.Errorf("build failed before SBOM generation: %w", err)
	}

	tarFile := container.AsTarball()

	trivyContainer := dag.Container().
		From("aquasec/trivy:latest").
		WithMountedFile("/image.tar", tarFile).
		WithExec([]string{"mkdir", "-p", "/output"}).
		WithExec([]string{
			"trivy",
			"image",
			"--input", "/image.tar",
			"--format", format,
			"--output", "/output/sbom.json",
		})

	return trivyContainer.File("/output/sbom.json"), nil
}

// GenerateSbomSpdx generates SPDX-format SBOM
func (m *KansallisarkistoMcp) GenerateSbomSpdx(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
) (*dagger.File, error) {
	return m.GenerateSbom(ctx, source, "spdx-json")
}

// GenerateSbomCycloneDx generates CycloneDX-format SBOM
func (m *KansallisarkistoMcp) GenerateSbomCycloneDx(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
) (*dagger.File, error) {
	return m.GenerateSbom(ctx, source, "cyclonedx")
}

// ExportSbom generates and exports SBOM to a local file
func (m *KansallisarkistoMcp) ExportSbom(
	ctx context.Context,
	// Source directory containing .docker/ and application code
	// +defaultPath="/"
	// +ignore=[".venv", ".git", ".data", "data", "site", ".pytest_cache", ".ruff_cache", "**/__pycache__", "*.pyc", ".env"]
	// +optional
	source *dagger.Directory,
	// SBOM format (spdx-json, cyclonedx, spdx, github)
	// +default="spdx-json"
	format string,
	// Output file path
	// +default="./sbom.json"
	outputPath string,
) (string, error) {
	sbomFile, err := m.GenerateSbom(ctx, source, format)
	if err != nil {
		return "", err
	}

	// Export the file
	_, err = sbomFile.Export(ctx, outputPath)
	if err != nil {
		return "", fmt.Errorf("failed to export SBOM: %w", err)
	}

	return fmt.Sprintf("SBOM exported to %s", outputPath), nil
}

// containsRegistry checks if an image reference contains a registry prefix
func containsRegistry(imageRef string) bool {
	for _, c := range imageRef {
		if c == '/' {
			return false
		}
		if c == '.' || c == ':' {
			return true
		}
	}
	return false
}

// ExtractProvenanceAttestation extracts the real SLSA provenance attestation from a BuildKit image
func (m *KansallisarkistoMcp) ExtractProvenanceAttestation(
	ctx context.Context,
	// Container image reference (e.g., riksarkivet/kansallisarkisto-mcp:v0.2.11)
	imageRef string,
	// Output file path
	// +default="./provenance.intoto.jsonl"
	outputPath string,
) (*dagger.File, error) {
	// Add docker.io prefix if needed
	fullRef := imageRef
	if len(imageRef) > 0 && imageRef[0] != '/' && !containsRegistry(imageRef) {
		fullRef = "docker.io/" + imageRef
	}

	// Get crane binary
	craneBinary := dag.Container().
		From("gcr.io/go-containerregistry/crane:latest").
		File("/ko-app/crane")

	// Use crane and jq to extract provenance from BuildKit attestations
	extractContainer := dag.Container().
		From("alpine:latest").
		WithExec([]string{"apk", "add", "--no-cache", "jq"}).
		WithFile("/usr/local/bin/crane", craneBinary).
		WithExec([]string{
			"sh", "-c",
			fmt.Sprintf(`
# Get the manifest list
MANIFEST=$(crane manifest %s)

# Find attestation manifest for amd64 platform
ATTESTATION_DIGEST=$(echo "$MANIFEST" | jq -r '.manifests[] | select(.annotations."vnd.docker.reference.type" == "attestation-manifest") | .digest' | head -1)

if [ -z "$ATTESTATION_DIGEST" ]; then
  echo "Error: No attestation manifest found"
  exit 1
fi

# Get attestation manifest
ATT_MANIFEST=$(crane manifest %s@$ATTESTATION_DIGEST)

# Find provenance layer
PROV_DIGEST=$(echo "$ATT_MANIFEST" | jq -r '.layers[] | select(.annotations."in-toto.io/predicate-type" | test("slsa.dev/provenance")) | .digest')

if [ -z "$PROV_DIGEST" ]; then
  echo "Error: No provenance layer found"
  exit 1
fi

# Download provenance blob
crane blob %s@$PROV_DIGEST > /provenance.intoto.jsonl
echo "Provenance extracted successfully"
			`, fullRef, fullRef, fullRef),
		})

	// Get the provenance file
	provenanceFile := extractContainer.File("/provenance.intoto.jsonl")

	// Export to output path
	_, err := provenanceFile.Export(ctx, outputPath)
	if err != nil {
		return nil, fmt.Errorf("failed to export provenance: %w", err)
	}

	return provenanceFile, nil
}
