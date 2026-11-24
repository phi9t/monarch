#!/bin/bash
# dev-entrypoint.sh - Container entrypoint for Monarch development environment
#
# This script:
# 1. Activates the conda monarch environment
# 2. Sets up dynamic library paths for PyTorch
# 3. Ensures RUSTFLAGS includes necessary configuration
# 4. Executes the provided command or starts an interactive shell

set -e

# =============================================================================
# Activate conda environment
# =============================================================================
source /opt/conda/etc/profile.d/conda.sh
conda activate monarch

# Export conda lib path for dynamic linking
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"

# =============================================================================
# Configure PyTorch/libtorch paths (for tensor_engine builds)
# =============================================================================
if [[ "${USE_TENSOR_ENGINE}" == "1" ]]; then
    # Get torch installation path
    TORCH_PATH=$(python -c "import torch; print(torch.__path__[0])" 2>/dev/null || echo "")

    if [[ -n "${TORCH_PATH}" ]]; then
        export LIBTORCH_LIB="${TORCH_PATH}/lib"
        export LIBTORCH_INCLUDE="${TORCH_PATH}/include:${TORCH_PATH}/include/torch/csrc/api/include"
        export LD_LIBRARY_PATH="${LIBTORCH_LIB}:${LD_LIBRARY_PATH}"

        # Detect C++11 ABI from torch
        CXX11_ABI=$(python -c "import torch; print(1 if torch._C._GLIBCXX_USE_CXX11_ABI else 0)" 2>/dev/null || echo "1")
        export _GLIBCXX_USE_CXX11_ABI="${CXX11_ABI}"
        export CXXFLAGS="-D_GLIBCXX_USE_CXX11_ABI=${CXX11_ABI}"
    fi

    # Configure CUDA paths if available
    if [[ -n "${CUDA_HOME}" ]] && [[ -d "${CUDA_HOME}" ]]; then
        export CUDA_LIB_DIR="${CUDA_HOME}/lib64"
        export LD_LIBRARY_PATH="${CUDA_LIB_DIR}:${LD_LIBRARY_PATH}"
        export LIBRARY_PATH="${CUDA_LIB_DIR}:/lib64:/usr/lib64:${LIBRARY_PATH:-}"

        # Add CUDA native library path to RUSTFLAGS if not already present
        if [[ ! "${RUSTFLAGS}" =~ "-L native=${CUDA_LIB_DIR}" ]]; then
            export RUSTFLAGS="${RUSTFLAGS} -L native=${CUDA_LIB_DIR}"
        fi
    fi
fi

# =============================================================================
# Ensure RUSTFLAGS includes tracing_unstable
# =============================================================================
if [[ ! "${RUSTFLAGS}" =~ "--cfg tracing_unstable" ]]; then
    export RUSTFLAGS="--cfg tracing_unstable ${RUSTFLAGS:-}"
fi

# Clean up any double spaces in RUSTFLAGS
export RUSTFLAGS=$(echo "${RUSTFLAGS}" | tr -s ' ')

# =============================================================================
# Set PYO3_PYTHON for Rust bindings
# =============================================================================
export PYO3_PYTHON="${CONDA_PREFIX}/bin/python"

# =============================================================================
# Development convenience functions (available in interactive shells)
# =============================================================================
show_env_info() {
    echo "=== Monarch Development Environment ==="
    echo ""
    echo "Python:  $(python --version 2>&1)"
    echo "Rust:    $(rustc --version 2>&1)"
    echo "Cargo:   $(cargo --version 2>&1)"

    if command -v nvcc &>/dev/null; then
        echo "CUDA:    $(nvcc --version 2>&1 | grep release | sed 's/.*release //' | sed 's/,.*//')"
    else
        echo "CUDA:    Not available"
    fi

    echo ""
    echo "PyTorch: $(python -c 'import torch; print(torch.__version__)' 2>/dev/null || echo 'Not installed')"
    echo "CUDA available: $(python -c 'import torch; print(torch.cuda.is_available())' 2>/dev/null || echo 'N/A')"
    echo ""
    echo "Environment:"
    echo "  USE_TENSOR_ENGINE: ${USE_TENSOR_ENGINE:-0}"
    echo "  CUDA_HOME:         ${CUDA_HOME:-not set}"
    echo "  LIBTORCH_ROOT:     ${LIBTORCH_ROOT:-not set}"
    echo "  CONDA_PREFIX:      ${CONDA_PREFIX}"
    echo ""
    echo "Quick Commands:"
    echo "  cargo build --workspace        # Build all Rust crates"
    echo "  cargo nextest run --workspace  # Run Rust tests"
    echo "  pip install -e .               # Install monarch (editable)"
    echo "  pytest python/tests/ -v -m 'not oss_skip'  # Run Python tests"
    echo ""
}

# Export the function so it's available in subshells
export -f show_env_info

# =============================================================================
# Execute command or start shell
# =============================================================================
if [[ $# -eq 0 ]]; then
    # No arguments - start interactive shell
    # Show environment info on first run
    show_env_info
    exec /bin/bash
else
    # Execute provided command
    exec "$@"
fi
