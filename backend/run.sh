#!/bin/sh
# Startup command on AWS Lambda (see aws/template.yaml). The Lambda Web
# Adapter layer forwards each request to this server on $PORT, so the app
# runs exactly as it does on Render.
cd "$(dirname "$0")"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m gunicorn -c gunicorn.conf.py app:app
