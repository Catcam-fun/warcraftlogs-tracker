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

floorpov.gg and www.floorpov.gg point at this CloudFront distribution, so this
is the live site. (The old Render host is no longer used.)

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

## The domain

`floorpov.gg` and `www.floorpov.gg` are alternate domain names on the
CloudFront distribution below. The domain stays registered at Porkbun.

## What's live now (built by hand in the console, Oct 2026)

The site was built by hand rather than from `template.yaml` (first as
staging, hence the `staging` in some names), in `us-east-1`. This repo is
public, so it never names the resources themselves: their IDs are in the
AWS console and in the repository secrets below.

| Piece | Where to find it | Settings |
|---|---|---|
| API | Lambda function (secret `LAMBDA_FUNCTION`) | Python 3.12, x86_64, handler `run.sh`, layer `LambdaAdapterLayerX86:30`, 3008 MB, 15 min; env vars as in `template.yaml` plus the Supabase keys, `ORIGIN_VERIFY_SECRET` and `WCL_PROXY_URL` (the deploy sets this one) |
| API URL | the function's URL, on an `api-*` alias of `$LATEST` | RESPONSE_STREAM. Auth AWS_IAM with CloudFront signing (origin access control `floorpov-api-lambda`) once Actions > *API URL lock* has run; NONE before that. If it leaks, run Actions > *Rotate API URL* |
| Site files | S3 bucket (secret `SITE_BUCKET`) | private, read by CloudFront only |
| CDN | CloudFront distribution (secret `CF_DISTRIBUTION_ID`), aliases `floorpov.gg` and `www.floorpov.gg` | origins: the bucket, and `floorpov-api` (the Lambda URL, custom header `X-Origin-Verify`, response and keep-alive timeouts 60 s); behaviors: `/api/*` (CachingDisabled, AllViewerExceptHostHeader, no compression, viewer-request function `floorpov-viewer-ip`) and Default (`floorpov-spa-rewrite`) |
| Warm-up | EventBridge schedule | every 5 min, payload `{"source": "floorpov.warm"}` |
| Budget | AWS Budgets | $10/month, email alerts at 50/80/100% |
| Circuit breaker | CloudFormation stack `floorpov-breaker` (`infra/breaker/breaker.yaml`) | see *Cost guards* below |

Repository secrets (Settings > Secrets and variables > Actions), all read by
`deploy-aws.yml`:

| Secret | What |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | the deploy role (setup above) |
| `LAMBDA_FUNCTION`, `SITE_BUCKET`, `CF_DISTRIBUTION_ID` | the resources above |
| `WCL_PROXY_URL` | the WarcraftLogs proxy (Cloudflare Worker); the deploy copies it into the function's settings |
| `REACT_APP_SUPABASE_URL`, `REACT_APP_SUPABASE_ANON_KEY`, `REACT_APP_TURNSTILE_SITE_KEY` | built into the site. The browser needs them, so they are readable in the live site's JavaScript; they stay out of the repo |

The account is on AWS's Free account plan (credits; no charges until it is
upgraded). Account-wide Lambda concurrency is 10, so reserved concurrency
can't be set (that 10 is itself the ceiling). The cost guards below keep a
flood from burning the credits (the account closes when they run out) or,
once upgraded, from running up a bill.

### Deploying an update by hand

- API: `infra/build-api-zip.sh api.zip` (backend's tracked files, no
  tests/scripts/migrations, plus its dependencies built for Lambda), then
  `aws lambda update-function-code --function-name <function> --zip-file fileb://api.zip`.
- Site: `npm run build` in `frontend/` with `REACT_APP_API_URL=same-origin`
  and the three `REACT_APP_*` values above (`frontend/.env.local` locally),
  drop `build/_redirects.txt`, `aws s3 sync build s3://<bucket> --delete`,
  then `aws cloudfront create-invalidation --distribution-id <distribution> --paths "/*"`.
- Sessions read the deploy key from `FLOORPOV_AWS_ACCESS_KEY_ID` /
  `FLOORPOV_AWS_SECRET_ACCESS_KEY` (environment variables; the plain
  `AWS_*` names are taken by the sandbox's proxy placeholders).

## Cost guards

### Art caching

The deploy uploads `art/` (backgrounds, boss tiles, loader video) with
`Cache-Control: public,max-age=604800`, so browsers keep it a week instead of
asking CloudFront again on every visit (`deploy-aws.yml`). A changed picture
reaches returning visitors within a week; give it a new file name to make it
immediate.

### API URL lock

Actions > *API URL lock* > Run workflow > `lock` (`infra/api-url-lock.sh`).
CloudFront then signs every `/api` request (origin access control) and the
Lambda URL refuses anything unsigned, so requests sent straight to the URL are
turned away by AWS before the function runs and cost nothing. The browser sends
its session in `X-Session-Token` (CloudFront's signature takes the
`Authorization` header) and a SHA-256 of every request body in
`x-amz-content-sha256`, which Lambda requires on signed POSTs
(`frontend/src/api.js`). The workflow checks the API through floorpov.gg after
each step and undoes the step if it stops answering. Run it again with
`unlock` to go back to a public URL guarded by `X-Origin-Verify` only.
*Rotate API URL* keeps a locked URL locked.

### Circuit breaker

`infra/breaker/breaker.yaml`, a CloudFormation stack (it uses SNS, CloudWatch
and Budgets, which the deploy role can't manage, so it's created by hand once).

- **Triggers**, all on the SNS topic `floorpov-breaker`: CloudFront requests
  over `RequestsPerMinute` (default 5,000) in 2 of 3 minutes; API Lambda
  invocations over `ApiCallsPerMinute` (default 300) in 2 of 3 minutes; and
  this month's actual cost over `MonthlyBudget` (default $10), credits left out.
  Costs reach AWS Budgets 8-12 hours late, so the two alarms do the fast work.
- **What it does**: emails you, and the `floorpov-breaker` Lambda
  (`infra/breaker/handler.js`) sets the API Lambda's reserved concurrency to 0
  (it can't run) and disables the CloudFront distribution (floorpov.gg is
  down). Nothing turns it back on by itself.
- **Reset**: Actions > *Reset breaker* > Run workflow. It removes the API's
  reserved concurrency and re-enables the distribution (about 5 minutes). By
  hand: Lambda console > the API function > Configuration > Concurrency > Edit
  > "Use unreserved account concurrency", and CloudFront console > the
  distribution > Enable. A budget trip doesn't fire again in the same month
  after a reset; the alarms re-arm once traffic is back to normal.
- **Install** (us-east-1): CloudFormation > Create stack > Upload
  `infra/breaker/breaker.yaml`, stack name `floorpov-breaker`, with the
  distribution ID and API function name (the `CF_DISTRIBUTION_ID` and
  `LAMBDA_FUNCTION` secrets) and your email. Tick the IAM acknowledgement.
  Confirm the subscription link AWS emails you.
- **Test** (switches the site off for a few minutes): CloudFormation > the
  stack > Outputs > `TopicArn`, then
  `aws sns publish --region us-east-1 --topic-arn <TopicArn> --message "breaker test"`.
  floorpov.gg goes down within a few minutes (the breaker's log group
  `/aws/lambda/floorpov-breaker` shows what it did); then run *Reset breaker*.
- **Code**: edit `handler.js`, then `node infra/breaker/build.mjs` copies it
  into the template; `node --test infra/breaker/handler.test.mjs` (run by the
  deploy) checks both.
