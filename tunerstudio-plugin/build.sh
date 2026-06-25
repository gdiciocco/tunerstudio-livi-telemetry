#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${ROOT_DIR}/build"
CLASSES_DIR="${BUILD_DIR}/classes"
OUT_JAR="${BUILD_DIR}/tunerstudio-livi-telemetry-plugin.jar"

if [[ "${1:-}" == "" ]]; then
  echo "Usage: ./build.sh /path/to/TunerStudioPluginAPI.jar" >&2
  echo "The javadoc jar is documentation only; compile against the API jar from your TunerStudio install." >&2
  exit 2
fi

API_JAR="$1"
rm -rf "${BUILD_DIR}"
mkdir -p "${CLASSES_DIR}"

javac -source 1.8 -target 1.8 -classpath "${API_JAR}" \
  -d "${CLASSES_DIR}" \
  $(find "${ROOT_DIR}/src" -name '*.java' -print)

jar cfm "${OUT_JAR}" "${ROOT_DIR}/manifest.mf" -C "${CLASSES_DIR}" .
echo "Built ${OUT_JAR}"

