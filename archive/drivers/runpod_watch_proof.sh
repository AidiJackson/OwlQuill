#!/bin/bash
# Background watcher: poll until the proof pod is terminal, then exit.
# Hard stop at 50 iterations (~50 min) as a final backstop; the in-pod watchdog
# (45 min) + main self-kill + poller cap are the primary guarantees.
cd "$(dirname "$0")" || exit 1
for i in $(seq 1 50); do
  OUT="$(python runpod_poll_proof.py 2>&1)"
  echo "[watch $i] $OUT"
  if echo "$OUT" | grep -qiE "POD GONE|TERMINATING|TERMINATED"; then
    echo "[watch] terminal state reached after $i polls"
    exit 0
  fi
  sleep 60
done
echo "[watch] iteration cap reached — forcing terminate"
python - <<'PY'
import json, runpod_proof_lib as L
st=json.load(open(L.STATE)); pid=st.get("pod_id")
try:
    L.terminate(pid); print("forced terminate sent for", pid)
except Exception as e:
    print("terminate err", e)
PY
