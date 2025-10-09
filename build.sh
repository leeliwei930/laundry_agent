#!/bin/bash

source .venv/bin/activate

mkdir -p build
mkdir -p build/_dependencies



pip install -r requirements.txt \
    --python-version 3.13 \
    --platform manylinux2014_aarch64 \
    --target ./build/_dependencies \
    --only-binary=:all:

