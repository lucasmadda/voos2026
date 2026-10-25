#!/bin/sh
# Captura local (launchd a cada 15 min) + "toca" os loaders ao vivo para o preview do
# Observable Framework reexecutá-los: o preview só reroda um loader quando o arquivo dele muda.
cd /Users/lucasgomesmaddalena/voos2026 || exit 1
export PYTHONPATH=/Users/lucasgomesmaddalena/voos2026/pipeline
.venv/bin/python -m voos.capture --site POA --site FOR --inmet --siros-diario
rc=$?
touch src/data/live/*.py
exit $rc
