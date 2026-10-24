#!/bin/sh
set -eu

export PYTHONPATH=/home/protected/webmentions/runtime/current
export BLYNGER_WEBMENTION_CONFIG=/home/protected/webmentions/config/receiver.json
exec /usr/local/bin/python3 -m webmentions.inbound_endpoint
