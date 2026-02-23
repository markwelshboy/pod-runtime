#!/usr/bin/env bash
set -euo pipefail

cd /app/ai-toolkit

mkdir -p datasets
mkdir -p config

cd /app/ai-toolkit/config

hff get training/5H1V_QIE2511_custom_prompt_halflr_double_rank.yaml
mv 5H1V_QIE2511_custom_prompt_halflr_double_rank.yaml config.yaml

cd /app/ai-toolkit/datasets

hff get training/5h1v.tar
tar -xvf 5h1v.tar

hff get training/5h1v_control_images.tar
tar -xvf 5h1v_control_images.tar

cd /app/ai-toolkit