#!/bin/bash
# postCreateCommand.sh - VS Code devcontainer setup script
#
# This script runs after the devcontainer is created to perform
# additional setup tasks.

set -e

echo "=== Monarch Development Environment Setup ==="
echo ""

# =============================================================================
# Activate conda environment
# =============================================================================
source /opt/conda/etc/profile.d/conda.sh
conda activate monarch

# =============================================================================
# Verify Python environment
# =============================================================================
echo "Python environment:"
python --version
echo "  Location: $(which python)"
echo ""

# =============================================================================
# Verify Rust toolchain
# =============================================================================
echo "Rust toolchain:"
rustc --version
cargo --version
echo ""

# =============================================================================
# Set up git safe directory (for mounted workspace)
# =============================================================================
git config --global --add safe.directory /workspace

# =============================================================================
# Fix SSH directory permissions (if mounted)
# =============================================================================
if [[ -d /root/.ssh ]]; then
    # SSH keys should be read-only mounted, just ensure the directory is accessible
    chmod 700 /root/.ssh 2>/dev/null || true
fi

# =============================================================================
# Create helpful aliases
# =============================================================================
cat >> /root/.bashrc << 'ALIASES'

# Monarch development aliases
alias mb='pip install -e .'
alias mt='pytest python/tests/ -v -m "not oss_skip"'
alias mr='cargo nextest run'
alias mf='cargo fmt && flake8 python/'
alias mc='cargo check --workspace'

# Helpful shortcuts
alias ll='ls -la'
alias ..='cd ..'
alias ...='cd ../..'

ALIASES

# =============================================================================
# Display environment info
# =============================================================================
echo "=== Environment Ready ==="
echo ""
echo "Build Commands:"
echo "  cargo build --workspace         # Build all Rust crates"
echo "  cargo check --workspace         # Check without building"
echo "  pip install -e .                # Install monarch (editable)"
echo ""
echo "Test Commands:"
echo "  cargo nextest run --workspace   # Run Rust tests"
echo "  pytest python/tests/ -v -m 'not oss_skip'  # Run Python tests"
echo ""
echo "Example Commands:"
echo "  cargo run --example sieve -p hyperactor_mesh"
echo "  cargo run --example dining_philosophers -p hyperactor_mesh"
echo ""
echo "Aliases: mb (build), mt (python tests), mr (rust tests), mf (format), mc (check)"
echo ""

# =============================================================================
# Check CUDA availability (if tensor_engine enabled)
# =============================================================================
if [[ "${USE_TENSOR_ENGINE}" == "1" ]]; then
    echo "CUDA Status:"
    python -c "import torch; print(f'  PyTorch CUDA: {torch.cuda.is_available()}')" 2>/dev/null || echo "  PyTorch CUDA: Not available"

    if command -v nvidia-smi &>/dev/null; then
        echo "  GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo 'Not detected')"
    fi
    echo ""
fi

echo "Ready for development!"
