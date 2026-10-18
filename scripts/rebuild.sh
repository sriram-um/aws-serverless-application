#!/usr/bin/env bash
# Recreates the whole deployment from the templates (after scripts/teardown.sh):
#   1. build the DAX client layer (pure Python, --no-deps) and the SAM application
#   2. deploy orders-serverless-app (us-east-1 + global table replica in us-west-2),
#      caching OFF (EnableCaching=false - DAX/VPC/API cache bill by the hour)
#   3. create the two Cognito test users, add user 1 to the 'admins' group, and write the
#      credentials + API URL to ~/.orders-test-user.env (outside the repo, chmod 600)
#   4. run scripts/smoke_test.sh against the new stack
# Every value that changes between deployments (API URL, user pool, app client) is read from
# stack outputs - nothing is hard-coded. Prerequisite: the CI bootstrap stack
# aws-serverless-application-github-oidc is only needed for GitHub Actions, not for this script.
# Usage: bash scripts/rebuild.sh        (~5-8 min; SAM CLI + Python 3.12 venv, no Docker)
#        SAM="/c/Program Files/Amazon/AWSSAMCLI/bin/sam.cmd" bash scripts/rebuild.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export AWS_PROFILE=default   # the shell may point at another account (playbook)
export AWS_DEFAULT_REGION=us-east-1
STACK=orders-serverless-app
SAM=${SAM:-sam}
PYTHON=${PYTHON:-.venv/Scripts/python}
[ -x "$PYTHON" ] || PYTHON=.venv/bin/python
[ -x "$PYTHON" ] || PYTHON=python

out() { aws cloudformation describe-stacks --stack-name $STACK \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
step() { echo; echo "===== $(date +%H:%M:%S) $*"; }

aws sts get-caller-identity --query Account --output text | grep -qx 977534234172 \
  || { echo "wrong AWS account - check the default profile"; exit 1; }

step "1/4 build"
PYTHON=$PYTHON bash scripts/build_dax_layer.sh
"$SAM" validate --lint
"$SAM" build

step "2/4 deploy $STACK (caching off)"
"$SAM" deploy --no-fail-on-empty-changeset \
  --parameter-overrides EnableCaching=false AppVersion="$(git rev-parse --short HEAD)"
POOL_ID=$(out UserPoolId)
CLIENT_ID=$(out UserPoolClientId)
API_URL=$(out ApiUrl)
echo "API $API_URL | user pool $POOL_ID | client $CLIENT_ID"

step "3/4 test users + ~/.orders-test-user.env"
PW1="Tst-$("$PYTHON" -c 'import secrets;print(secrets.token_hex(8))')-Aa1!"
PW2="Tst-$("$PYTHON" -c 'import secrets;print(secrets.token_hex(8))')-Bb2!"
for pair in "testuser@example.com:$PW1" "testuser2@example.com:$PW2"; do
  user=${pair%%:*}; pw=${pair#*:}
  aws cognito-idp admin-create-user --user-pool-id "$POOL_ID" --username "$user" \
    --user-attributes Name=email,Value="$user" Name=email_verified,Value=true \
    --message-action SUPPRESS >/dev/null 2>&1 || echo "$user already exists - resetting password"
  aws cognito-idp admin-set-user-password --user-pool-id "$POOL_ID" --username "$user" \
    --password "$pw" --permanent
done
aws cognito-idp admin-add-user-to-group --user-pool-id "$POOL_ID" \
  --username testuser@example.com --group-name admins
umask 077
printf 'USER_POOL_ID=%s\nCLIENT_ID=%s\nAPI_URL=%s\nTEST_USER=%s\nTEST_PASSWORD=%s\nTEST_USER2=%s\nTEST_PASSWORD2=%s\n' \
  "$POOL_ID" "$CLIENT_ID" "$API_URL" testuser@example.com "$PW1" testuser2@example.com "$PW2" \
  > ~/.orders-test-user.env
echo "wrote ~/.orders-test-user.env (testuser@example.com is in 'admins')"

step "4/4 smoke test"
PATH="$(dirname "$PYTHON"):$PATH" bash scripts/smoke_test.sh
echo
echo "Rebuilt. Dashboard: $(out DashboardUrl)"
echo "Optional: EnableCaching=true for DAX + API cache (bills hourly), Power Tuning from SAR (README)."
