#!/usr/bin/env bash

# Retry an operational command without logging its arguments. Callers may pass
# private configuration through the environment without exposing it in logs.
retry_with_backoff() {
  local attempts=$1
  local base_delay=$2
  shift 2

  local attempt=1
  local status=0
  while true; do
    if "$@"; then
      return 0
    else
      status=$?
    fi

    if test "$attempt" -ge "$attempts"; then
      echo "operation failed after ${attempts} attempts (status ${status})" >&2
      return "$status"
    fi

    local delay=$((base_delay * attempt))
    echo "operation attempt ${attempt}/${attempts} failed (status ${status}); retrying in ${delay}s" >&2
    sleep "$delay"
    attempt=$((attempt + 1))
  done
}

# A periodic RDS mirror must not stop durable local collection. The final sync
# remains strict because callers invoke it directly instead of through here.
run_nonfatal() {
  local operation=$1
  shift

  local status=0
  if "$@"; then
    return 0
  else
    status=$?
  fi
  echo "non-fatal ${operation} failure (status ${status}); local collection will continue" >&2
  return 0
}
