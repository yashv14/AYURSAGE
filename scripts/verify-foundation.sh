#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

fail() {
  printf 'foundation verification failed: %s\n' "$1" >&2
  exit 1
}

tracked_model_artifacts="$({ git ls-files '*.pkl' '*.pickle' '*.joblib' '*.onnx' '*.h5' '*.pt' '*.pth'; } || true)"
[[ -z "$tracked_model_artifacts" ]] || fail "model binaries are tracked:\n$tracked_model_artifacts"

tracked_environment_files="$({ git ls-files '.env' '.env.*' | grep -v '^\.env\.example$'; } || true)"
[[ -z "$tracked_environment_files" ]] || fail "non-example environment files are tracked:\n$tracked_environment_files"

tracked_private_keys="$({ git ls-files '*.pem' '*.key' '*.p12' '*.pfx'; } || true)"
[[ -z "$tracked_private_keys" ]] || fail "private-key or certificate bundle files are tracked:\n$tracked_private_keys"

if git grep -I -E -- 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY' -- . >/dev/null; then
  fail "private-key material appears in a tracked file"
fi

if git grep -I -E -- '^[[:space:]]*def[[:space:]]+predict_single[[:space:]]*\(' -- . >/dev/null; then
  fail "predict_single() has been recreated"
fi

if git grep -I -E -- 'DummyClassifier|dummy[[:space:]_-]*model' -- ':!docs/**' ':!AGENTS.md' ':!scripts/verify-foundation.sh' >/dev/null; then
  fail "dummy model code appears in the application"
fi

grep -qx 'ML_ENABLED=false' .env.example || fail "the example environment does not keep ML disabled"

printf 'Foundation safety checks passed.\n'
