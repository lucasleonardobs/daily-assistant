#!/bin/sh
# Espera o deploy que o `railway up --ci` acabou de disparar ficar no ar.
# O --ci só espera o BUILD; este script espera a nova versão passar no healthcheck do Railway.
#
# Uso: wait-railway-deploy.sh <id-do-deploy-anterior> [servico]
# Precisa de RAILWAY_TOKEN (token de projeto) ou de uma CLI já logada e vinculada ao projeto.
set -eu

PREVIOUS_ID="${1:?informe o id do deploy anterior}"
SERVICE="${2:-daily-app}"
TIMEOUT="${DEPLOY_TIMEOUT_SECONDS:-600}"
INTERVAL=10
elapsed=0

# Imprime "<id> <status>" do deploy mais recente.
latest() {
  railway deployment list --service "$SERVICE" --limit 1 --json | python3 -c '
import json, sys
deployments = json.load(sys.stdin)
print(deployments[0]["id"], deployments[0]["status"]) if deployments else print("none none")'
}

while [ "$elapsed" -lt "$TIMEOUT" ]; do
  # Uma falha passageira da CLI/API não derruba a espera: tenta de novo no próximo ciclo.
  out=$(latest 2>/dev/null) || out="none none"
  id=${out% *}
  status=${out#* }
  if [ "$id" = "$PREVIOUS_ID" ] || [ "$id" = "none" ]; then
    echo "[${elapsed}s] aguardando o Railway registrar o novo deploy..."
  else
    echo "[${elapsed}s] deploy $id: $status"
    case "$status" in
      SUCCESS) exit 0 ;;
      FAILED|CRASHED|REMOVED|SKIPPED) echo "O deploy $id terminou como $status." >&2; exit 1 ;;
    esac
  fi
  sleep "$INTERVAL"
  elapsed=$((elapsed + INTERVAL))
done

echo "Tempo esgotado (${TIMEOUT}s) esperando o deploy ficar no ar." >&2
exit 1
