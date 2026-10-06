#!/bin/bash
# Lambda entry point (infra/template.yaml): the Lambda Web Adapter layer starts
# this, then forwards each request to gunicorn on $PORT. gunicorn.conf.py in
# this folder supplies the rest of the server settings.
# MALLOC_ARENA_MAX: glibc gives each of the many request and fetch threads its
# own memory arena and keeps them; two arenas take a Phoenix-sized analysis's
# peak from about 1.3 GB to about 0.8 GB at the same speed.
# PYTHONUNBUFFERED: the app's own log lines (cache failures, WCL warnings) reach
# CloudWatch as they happen instead of sitting in a pipe buffer.
MALLOC_ARENA_MAX=${MALLOC_ARENA_MAX:-2} \
    PYTHONUNBUFFERED=1 \
    PATH=$PATH:$LAMBDA_TASK_ROOT/bin \
    PYTHONPATH=$PYTHONPATH:/opt/python:$LAMBDA_RUNTIME_DIR \
    exec python -m gunicorn app:app
