#!/bin/bash
# Lambda entry point (infra/template.yaml): the Lambda Web Adapter layer starts
# this, then forwards each request to gunicorn on $PORT. gunicorn.conf.py in
# this folder supplies the rest of the server settings.
PATH=$PATH:$LAMBDA_TASK_ROOT/bin \
    PYTHONPATH=$PYTHONPATH:/opt/python:$LAMBDA_RUNTIME_DIR \
    exec python -m gunicorn app:app
