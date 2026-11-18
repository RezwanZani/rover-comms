#!/usr/bin/env bash
# run_base_station.sh -- Launches all Base Station services in the correct order
cd "$(dirname "$0")"
python3 launch_base_station.py "$@"
