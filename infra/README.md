# Floor Pov on AWS

`template.yaml` runs the whole site on AWS in `us-east-1`:

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

Each stage (`staging`, `production`) is its own stack with its own address,
so the live site doesn't change until the domain is pointed at AWS.

## One-time setup

1. **Deploy role.** AWS console, region **N. Virginia (us-east-1)** >
   CloudFormation > Create stack > *Upload a template file* >
   `infra/github-deploy-role.yaml`. Stack name: `floorpov-github-deploy`.
   Set `CreateOidcProvider` to `false` only if IAM > Identity providers
   already lists `token.actions.githubusercontent.com`. Tick the IAM
   acknowledgement and create it. Copy the **RoleArn** from the Outputs tab.
2. **GitHub secrets.** Repository > Settings > Secrets and variables >
   Actions > New repository secret, one each:
   - `AWS_DEPLOY_ROLE_ARN`: the RoleArn from step 1
   - `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`: the same
     values the Render service has
   - `ORIGIN_VERIFY_SECRET`: any 32+ random characters (a password
     generator is fine); you never need to type it again
3. **Deploy.** Actions > *Deploy to AWS* > Run workflow > stage `staging`.
   The run tests the code, deploys, and ends with the site's address.

## Later: the domain

At switch time: a Route 53 hosted zone for `floorpov.gg`, a certificate,
and the domain on the production CloudFront distribution. Then, at Porkbun,
the domain's nameservers change to the four Route 53 gives. The domain stays
registered at Porkbun.
