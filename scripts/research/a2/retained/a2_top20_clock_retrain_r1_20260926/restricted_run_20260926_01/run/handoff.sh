#!/bin/sh
set -eu
python /bundle/isolation_probe.py
if [ -z "${R1_EXPECTED_MANIFEST_SHA256:-}" ]; then
  echo 'EXTERNAL_BUNDLE_SEAL_REQUIRED' >&2
  exit 2
fi
python -c 'import hashlib,os; p="/bundle/input_manifest.json"; expected=os.environ["R1_EXPECTED_MANIFEST_SHA256"]; actual=hashlib.sha256(open(p,"rb").read()).hexdigest(); assert actual==expected, "BUNDLE_SEAL_MISMATCH"'
if [ -e /out/run ]; then
  echo 'NON_OVERWRITE_OUTPUT_EXISTS' >&2
  exit 2
fi
mkdir /out/run
cp -a /bundle/. /out/run/
python -c 'import hashlib,os; p="/out/run/input_manifest.json"; expected=os.environ["R1_EXPECTED_MANIFEST_SHA256"]; actual=hashlib.sha256(open(p,"rb").read()).hexdigest(); assert actual==expected, "CONSUMED_COPY_SEAL_MISMATCH"'
cd /out/run
R1_VERIFIED_ISOLATION=1 python run_training.py
