# Floor Pov on AWS

The whole site runs on AWS in `us-east-1`:

- **Website:** the React build in a private S3 bucket, served by CloudFront.
  A CloudFront Function sends React routes (`/results`, `/analyze`, ...) to
  `index.html`.
- **API:** the Flask backend, unchanged, on Lambda through the
  [Lambda Web Adapter](https://github.com/aws/aws-lambda-web-adapter)
  (`backend/run.sh` starts gunicorn). It's served at `/api/*` on the same
  CloudFront address, through a Lambda function URL in streaming mode, so an
  analysis streams for up to 15 minutes. The API sends a keepalive every 15
  seconds (`backend/streaming.py`) so CloudFront doesn't close a quiet stream.
- **Locked to CloudFront:** CloudFront adds a secret `X-Origin-Verify` header;
  the API refuses anything without it (`backend/origin.py`), except the
  adapter's own health check and warm-up calls. A CloudFront Function passes
  the visitor's IP as `X-Viewer-Ip` for the rate limits (`backend/ratelimit.py`).
- **Warm:** a schedule pings the function every 5 minutes so a copy is usually
  ready. AWS can still recycle it, so an occasional first request is slower.
- **Unchanged:** Supabase, and the WarcraftLogs proxy.

It has its own CloudFront address, so floorpov.gg doesn't change until the
domain is pointed at AWS.

## Deploying (GitHub Actions)

`.github/workflows/deploy-aws.yml` deploys to the hand-built resources below
on every push to `main` (so merging a pull request deploys), and by hand from
Actions > *Deploy to AWS* > Run workflow. It runs the backend and frontend
tests, builds the API zip (`infra/build-api-zip.sh`) and the site, updates
the Lambda code, uploads the site to S3, refreshes CloudFront, and checks
the live address. It changes code only: the function's settings and secrets
stay as set in the console.

One-time setup, so GitHub can deploy without a stored AWS key:

1. **Deploy role.** AWS console, region **N. Virginia (us-east-1)** >
   CloudFormation > Create stack > *Upload a template file* >
   `infra/github-deploy-role.yaml`. Stack name: `floorpov-github-deploy`.
   Set `CreateOidcProvider` to `false` only if IAM > Identity providers
   already lists `token.actions.githubusercontent.com`. Tick the IAM
   acknowledgement and create it. Copy the **RoleArn** from the Outputs tab.
2. **GitHub secret.** Repository > Settings > Secrets and variables >
   Actions > New repository secret: `AWS_DEPLOY_ROLE_ARN`, the RoleArn
   from step 1.

`template.yaml` describes the same setup as a SAM stack; it is a reference
for rebuilding it, not what is live.

## Later: the domain

At switch time: a Route 53 hosted zone for `floorpov.gg`, a certificate,
and the domain on the production CloudFront distribution. Then, at Porkbun,
the domain's nameservers change to the four Route 53 gives. The domain stays
registered at Porkbun.

## What's live now (built by hand in the console, Oct 2026)

The staging site was built by hand rather than from `template.yaml`; these
are the real resources (account REDACTED, us-east-1):

| Piece | Name / ID | Settings |
|---|---|---|
| API | Lambda `REDACTED` | Python 3.12, x86_64, handler `run.sh`, layer `LambdaAdapterLayerX86:30`, 3008 MB, 15 min; env vars as in `template.yaml` plus the Supabase keys and `ORIGIN_VERIFY_SECRET` |
| API URL | `REDACTED/` | auth NONE, RESPONSE_STREAM |
| Site files | S3 bucket `REDACTED` | private, read by CloudFront only |
| CDN | CloudFront `REDACTED`, `REDACTED` | origins: the bucket, and `floorpov-api` (the Lambda URL, custom header `X-Origin-Verify`, response and keep-alive timeouts 60 s); behaviors: `/api/*` (CachingDisabled, AllViewerExceptHostHeader, no compression, viewer-request function `floorpov-viewer-ip`) and Default (`floorpov-spa-rewrite`) |
| Warm-up | EventBridge schedule `REDACTED` | every 5 min, payload `{"source": "floorpov.warm"}` |
| Budget | `REDACTED` | $10/month, email alerts at 50/80/100% |

The account is on AWS's Free account plan (credits; no charges until it is
upgraded). Account-wide Lambda concurrency is 10, so reserved concurrency
can't be set; a budget kill switch, once the account is upgraded, should
switch the function URL's auth to AWS_IAM instead.

### Deploying an update by hand

- API: `infra/build-api-zip.sh api.zip` (backend's tracked files, no
  tests/scripts/migrations, plus its dependencies built for Lambda), then
  `aws lambda update-function-code --function-name REDACTED --zip-file fileb://api.zip`.
- Site: `REACT_APP_API_URL=same-origin npm run build` in `frontend/`, drop
  `build/_redirects.txt`, `aws s3 sync build s3://REDACTED --delete`,
  then `aws cloudfront create-invalidation --distribution-id REDACTED --paths "/*"`.
- Sessions read the deploy key from `FLOORPOV_AWS_ACCESS_KEY_ID` /
  `FLOORPOV_AWS_SECRET_ACCESS_KEY` (environment variables; the plain
  `AWS_*` names are taken by the sandbox's proxy placeholders).
