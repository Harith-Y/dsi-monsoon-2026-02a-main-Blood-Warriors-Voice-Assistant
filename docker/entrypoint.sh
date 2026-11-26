#!/bin/sh
# First start: copy the reviewed knowledge base into the data volume. After that the volume's copy is the
# live one (coordinators change it by voice on /teach), so a rebuilt image never overwrites their changes.
# To start again from the repository's KB, delete /data/kb (and /data/index) and restart.
set -e

mkdir -p /data/kb /data/runtime /data/index /data/tts_cache /data/logs
for f in entries.json question_variants.json; do
  if [ ! -f "/data/kb/$f" ]; then
    cp "/app/kb/$f" "/data/kb/$f"
    echo "Seeded /data/kb/$f from the image"
  fi
done

if [ -z "$GROQ_API_KEY" ]; then echo "Warning: GROQ_API_KEY is not set; answers will go to a coordinator." >&2; fi
if [ -z "$HF_TOKEN" ]; then echo "Warning: HF_TOKEN is not set; Telugu and Hindi speech-to-text cannot load." >&2; fi

echo "Open http://localhost:8000 (caregivers), /dashboard and /teach (coordinators). Not 0.0.0.0: browsers block the mic there."
exec "$@"
