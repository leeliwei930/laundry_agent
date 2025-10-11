#!/bin/bash

source .venv/bin/activate

mkdir -p build
mkdir -p build/_dependencies
mkdir -p build/models

pip install -r requirements.txt \
    --python-version 3.13 \
    --platform manylinux2014_aarch64 \
    --target ./build/_dependencies \
    --only-binary=:all:

# Copy Lambda handler files
cp src/security_cam_analyser_agent.py build/
cp src/laundry_monitoring_agent.py build/

# Copy model files
cp src/models/analyze_response.py build/models/
cp src/models/laundry_analysis_response.py build/models/
cp src/models/analyze_response_schema.json build/models/

# Create __init__.py for models package
touch build/models/__init__.py

