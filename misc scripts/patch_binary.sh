#!/usr/bin/env bash
#
# patch-binary.sh
#
# Safely patch a binary by replacing one sequence of hex bytes with another.
# Using uppercase hex, removing newlines, and optionally padding if the new
# string is shorter.
#
# Variables (edit as needed inside this script):
#   BINARY_FILE
#   ORIG_HEX
#   REPLACEMENT_HEX
#
# Steps:
#   1) Check if BINARY_FILE exists
#   2) Check if already patched or if the original is missing
#   3) Enforce even-length hex
#   4) Pad if shorter, error if longer
#   5) Dump entire file as uppercase hex (no newlines), sed the replacement
#   6) Convert back to binary
#

set -eu -o pipefail

# ------------------------------------------------------------------------------
# 0) Define your variables here
# ------------------------------------------------------------------------------
BINARY_FILE="/usr/local/bin/mybinary"
ORIG_HEX="DEADBEEF"           # Must be uppercase for direct matching
REPLACEMENT_HEX="BAADBE"      # Example: shorter than ORIG_HEX

# ------------------------------------------------------------------------------
# 1) File checks
# ------------------------------------------------------------------------------
if [[ ! -s "$BINARY_FILE" ]]; then
  echo "Error: File '$BINARY_FILE' does not exist or is empty."
  exit 1
fi

# ------------------------------------------------------------------------------
# 2) Check if already patched or if the original is missing.
#    We'll do an uppercase, no-newline hex dump -> grep.
# ------------------------------------------------------------------------------
UPPER_HEX_DUMP="$(mktemp /tmp/upper_hex_dump.XXXXXX)"
xxd -p -u "$BINARY_FILE" | tr -d '\n' > "$UPPER_HEX_DUMP"

if grep -q "$REPLACEMENT_HEX" "$UPPER_HEX_DUMP"; then
  echo "Info: '$BINARY_FILE' is already patched (replacement '$REPLACEMENT_HEX' found)."
  rm -f "$UPPER_HEX_DUMP"
  exit 0
fi

if ! grep -q "$ORIG_HEX" "$UPPER_HEX_DUMP"; then
  echo "Warning: Original hex '$ORIG_HEX' not found in '$BINARY_FILE'; nothing to patch."
  rm -f "$UPPER_HEX_DUMP"
  exit 0
fi

# ------------------------------------------------------------------------------
# 3) Ensure both ORIG_HEX and REPLACEMENT_HEX have an even number of hex digits
# ------------------------------------------------------------------------------
ORIG_LEN=${#ORIG_HEX}
REPL_LEN=${#REPLACEMENT_HEX}

if (( ORIG_LEN % 2 != 0 )) || (( REPL_LEN % 2 != 0 )); then
  echo "Error: ORIG_HEX and REPLACEMENT_HEX must have an even number of hex digits."
  rm -f "$UPPER_HEX_DUMP"
  exit 1
fi

# ------------------------------------------------------------------------------
# 4) If REPLACEMENT_HEX is longer, abort; if shorter, pad with '0's (null bytes).
# ------------------------------------------------------------------------------
if (( REPL_LEN > ORIG_LEN )); then
  echo "Error: REPLACEMENT_HEX ($REPLACEMENT_HEX) is longer than ORIG_HEX ($ORIG_HEX)."
  echo "       Patching would overwrite extra bytes. Aborting."
  rm -f "$UPPER_HEX_DUMP"
  exit 1
elif (( REPL_LEN < ORIG_LEN )); then
  DIFF=$(( ORIG_LEN - REPL_LEN ))
  PADDING="$(printf '%*s' "$DIFF" '' | tr ' ' '0')"   # a string of '0' repeated DIFF times
  REPLACEMENT_HEX="${REPLACEMENT_HEX}${PADDING}"
  echo "Info: Padded REPLACEMENT_HEX to match length of ORIG_HEX:"
  echo "      $REPLACEMENT_HEX"
fi

# ------------------------------------------------------------------------------
# 5) Perform the replacement on the single-line uppercase hex dump
#    Then re-convert it back into binary with xxd -r -p
# ------------------------------------------------------------------------------
sed -i "s/$ORIG_HEX/$REPLACEMENT_HEX/g" "$UPPER_HEX_DUMP"

# Convert it back into binary, overwriting the original
xxd -r -p "$UPPER_HEX_DUMP" "$BINARY_FILE"

rm -f "$UPPER_HEX_DUMP"
echo "Success: Patched '$BINARY_FILE' from $ORIG_HEX to $REPLACEMENT_HEX."
