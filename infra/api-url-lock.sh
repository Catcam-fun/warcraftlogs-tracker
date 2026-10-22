#!/bin/bash
# Locks or unlocks the API's Lambda URL so only CloudFront can call it.
# Usage: infra/api-url-lock.sh lock|unlock   (run by .github/workflows/api-url-lock.yml)
# Needs FUNCTION, DISTRIBUTION, SITE_URL, ORIGIN_ID and OAC_NAME, and AWS credentials.
#
# Lock order keeps the site up throughout: CloudFront starts signing while the
# URL is still public, then the URL switches to AWS_IAM. Each step is checked
# through floorpov.gg and undone if the API stops answering.
set -euo pipefail
mode=${1:?usage: api-url-lock.sh lock|unlock}

acct=$(aws sts get-caller-identity --query Account --output text)
echo "::add-mask::$acct"
dist_arn="arn:aws:cloudfront::$acct:distribution/$DISTRIBUTION"

# The function URL (and its alias) that CloudFront's API origin points at.
aws cloudfront get-distribution-config --id "$DISTRIBUTION" > dist.json
host=$(jq -r --arg id "$ORIGIN_ID" '.DistributionConfig.Origins.Items[] | select(.Id == $id) | .DomainName' dist.json)
echo "::add-mask::$host"
url_arn=$(aws lambda list-function-url-configs --function-name "$FUNCTION" \
  --query "FunctionUrlConfigs[?contains(FunctionUrl, '$host')].FunctionArn | [0]" --output text)
[ -n "$url_arn" ] && [ "$url_arn" != None ] || { echo "no function URL matches the API origin"; exit 1; }
qualifier="${url_arn##*:}"
fn=(--function-name "$FUNCTION")
[ "$qualifier" = "$FUNCTION" ] || fn+=(--qualifier "$qualifier")

set_origin_oac() {  # $1: the OAC id, or "" to stop signing
  aws cloudfront get-distribution-config --id "$DISTRIBUTION" > dist.json
  local etag
  etag=$(jq -r .ETag dist.json)
  jq --arg id "$ORIGIN_ID" --arg oac "$1" \
    '.DistributionConfig | (.Origins.Items[] | select(.Id == $id) | .OriginAccessControlId) = $oac' \
    dist.json > config.json
  aws cloudfront update-distribution --id "$DISTRIBUTION" --if-match "$etag" \
    --distribution-config file://config.json > /dev/null
  rm -f config.json
  echo "waiting for CloudFront to roll the change out (a few minutes)"
  aws cloudfront wait distribution-deployed --id "$DISTRIBUTION"
}

allow() {  # statement id, then add-permission arguments; replaces an existing statement
  local sid=$1; shift
  aws lambda remove-permission "${fn[@]}" --statement-id "$sid" > /dev/null 2>&1 || true
  aws lambda add-permission "${fn[@]}" --statement-id "$sid" "$@" > /dev/null
}
revoke() { aws lambda remove-permission "${fn[@]}" --statement-id "$1" > /dev/null 2>&1 || true; }

status() { curl -s -o /dev/null -w '%{http_code}' "$@" || echo 000; }

# The API answers through floorpov.gg, including a signed POST (an empty share
# request: the API refuses it with 400 and stores nothing). 403 there means
# Lambda rejected CloudFront's signature.
site_ok() {
  local code=000
  for _ in 1 2 3 4 5 6; do
    code=$(status "$SITE_URL/api/health")
    [ "$code" = 200 ] && break
    sleep 10
  done
  echo "GET /api/health through CloudFront: $code"
  [ "$code" = 200 ] || return 1
  local body='{}' hash
  hash=$(printf %s "$body" | sha256sum | cut -d' ' -f1)
  code=$(status -X POST -H 'Content-Type: application/json' -H "x-amz-content-sha256: $hash" \
    --data "$body" "$SITE_URL/api/share")
  echo "POST /api/share through CloudFront: $code"
  [ "$code" = 400 ]
}

public_access() {
  allow FunctionURLAllowPublicAccess --action lambda:InvokeFunctionUrl \
    --principal '*' --function-url-auth-type NONE
  allow FunctionURLInvokeAllowPublicAccess --action lambda:InvokeFunction \
    --principal '*' --invoked-via-function-url
}

if [ "$mode" = lock ]; then
  oac=$(aws cloudfront list-origin-access-controls \
    --query "OriginAccessControlList.Items[?Name=='$OAC_NAME'].Id | [0]" --output text)
  if [ -z "$oac" ] || [ "$oac" = None ]; then
    oac=$(aws cloudfront create-origin-access-control --origin-access-control-config \
      "Name=$OAC_NAME,Description=floorpov.gg signs its API requests,SigningProtocol=sigv4,SigningBehavior=always,OriginAccessControlOriginType=lambda" \
      --query OriginAccessControl.Id --output text)
  fi
  allow CloudFrontInvokeFunctionUrl --action lambda:InvokeFunctionUrl \
    --principal cloudfront.amazonaws.com --source-arn "$dist_arn"
  allow CloudFrontInvokeFunction --action lambda:InvokeFunction \
    --principal cloudfront.amazonaws.com --source-arn "$dist_arn"

  echo "1/2: CloudFront signs API requests (the URL is still public)"
  set_origin_oac "$oac"
  if ! site_ok; then
    echo "the API failed with signing on; switching signing off again"
    set_origin_oac ""
    exit 1
  fi

  echo "2/2: the URL refuses unsigned requests"
  aws lambda update-function-url-config "${fn[@]}" --auth-type AWS_IAM > /dev/null
  sleep 20
  direct=$(status "https://$host/api/health")
  echo "GET /api/health straight to the Lambda URL: $direct"
  if site_ok && [ "$direct" = 403 ]; then
    revoke FunctionURLAllowPublicAccess
    revoke FunctionURLInvokeAllowPublicAccess
    echo "### API URL locked: only CloudFront can call it" >> "$GITHUB_STEP_SUMMARY"
  else
    echo "the locked API failed its checks; unlocking"
    aws lambda update-function-url-config "${fn[@]}" --auth-type NONE > /dev/null
    exit 1
  fi
else
  echo "1/2: the URL accepts unsigned requests again"
  public_access
  aws lambda update-function-url-config "${fn[@]}" --auth-type NONE > /dev/null
  echo "2/2: CloudFront stops signing"
  set_origin_oac ""
  revoke CloudFrontInvokeFunctionUrl
  revoke CloudFrontInvokeFunction
  site_ok
  echo "### API URL unlocked (public, guarded by X-Origin-Verify)" >> "$GITHUB_STEP_SUMMARY"
fi
rm -f dist.json
