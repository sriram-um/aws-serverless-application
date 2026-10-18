#!/usr/bin/env bash
# Deletes the deployment so nothing keeps billing:
#   1. app stack orders-serverless-app (us-east-1) - Lambdas, API, WAF, Cognito, dashboard,
#      OrderStats, DLQ, layers and the Orders global table *including its us-west-2 replica*
#      (and the DAX/VPC resources, if EnableCaching was left on)
#   2. Lambda Power Tuning stack (exercise 8), plus the log groups its functions created
#   3. checks that nothing billable is left in either region
# Kept on purpose (free): the CI bootstrap stack aws-serverless-application-github-oidc (the
# GitHub secrets stay valid for scripts/rebuild.sh) and the shared SAM artifact bucket.
# Pushes to main skip the deploy while the app stack doesn't exist.
# Usage: bash scripts/teardown.sh --yes        (~5-10 min; deletes all order data)
set -euo pipefail
cd "$(dirname "$0")/.."
[ "${1:-}" = "--yes" ] || { echo "This deletes all order data in both regions. Re-run with --yes."; exit 1; }
export AWS_PROFILE=default   # the shell may point at another account (playbook)
export AWS_DEFAULT_REGION=us-east-1
export MSYS_NO_PATHCONV=1    # Git Bash: keep /aws/lambda/... log group names intact
STACK=orders-serverless-app
TUNING=serverlessrepo-lambda-power-tuning
REPLICA=us-west-2
SAM=${SAM:-sam}
step() { echo; echo "===== $(date +%H:%M:%S) $*"; }
exists() { aws cloudformation describe-stacks --region "$1" --stack-name "$2" >/dev/null 2>&1; }

aws sts get-caller-identity --query Account --output text | grep -qx 977534234172 \
  || { echo "wrong AWS account - check the default profile"; exit 1; }

step "1/3 app stack $STACK (global table + $REPLICA replica go with it)"
if exists us-east-1 $STACK; then
  "$SAM" delete --stack-name $STACK --region us-east-1 --profile default --no-prompts
else
  echo "not deployed"
fi

step "2/3 Lambda Power Tuning stack + its log groups"
if exists us-east-1 $TUNING; then
  aws cloudformation delete-stack --stack-name $TUNING
  aws cloudformation wait stack-delete-complete --stack-name $TUNING
fi
for g in $(aws logs describe-log-groups --log-group-name-prefix /aws/lambda/$TUNING \
             --query 'logGroups[].logGroupName' --output text); do
  aws logs delete-log-group --log-group-name "$g" && echo "deleted $g"
done

step "3/3 check - everything below should be empty"
for region in us-east-1 $REPLICA; do
  echo "$region stacks:  $(aws cloudformation list-stacks --region $region \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE DELETE_FAILED \
    --query "StackSummaries[?starts_with(StackName,'$STACK') || starts_with(StackName,'$TUNING')].StackName" --output text)"
  echo "$region tables:  $(aws dynamodb list-tables --region $region --query "TableNames[?starts_with(@,'$STACK')]" --output text)"
done
echo "DAX clusters:     $(aws dax describe-clusters --query 'Clusters[].ClusterName' --output text)"
echo "tagged VPCs:      $(aws ec2 describe-vpcs --filters Name=tag:project,Values=serverless-orders --query 'Vpcs[].VpcId' --output text)"
echo "SQS queues:       $(aws sqs list-queues --queue-name-prefix $STACK --query 'QueueUrls' --output text)"
echo "Lambda functions: $(aws lambda list-functions --query "Functions[?starts_with(FunctionName,'$STACK') || starts_with(FunctionName,'$TUNING')].FunctionName" --output text)"
echo "REST APIs:        $(aws apigateway get-rest-apis --query "items[?starts_with(name,'$STACK')].name" --output text)"
echo "WAF web ACLs:     $(aws wafv2 list-web-acls --scope REGIONAL --query "WebACLs[?starts_with(Name,'$STACK')].Name" --output text)"
echo "Cognito pools:    $(aws cognito-idp list-user-pools --max-results 60 --query "UserPools[?starts_with(Name,'$STACK')].Name" --output text)"
echo "log groups:       $(aws logs describe-log-groups --log-group-name-prefix /aws/lambda/$STACK --query 'logGroups[].logGroupName' --output text)"
echo
echo "Kept (free): stack aws-serverless-application-github-oidc, the SAM artifact bucket, GitHub secrets."
echo "Recreate with: bash scripts/rebuild.sh"
