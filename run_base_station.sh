#!/usr/bin/env bash
# run_base_station.sh -- Launches all Base Station services from project root
cd "$(dirname "$0")/base_station"
exec python3 launch_base_station.py "$@"
