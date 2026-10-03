# Floor Pov on AWS

The site runs on three AWS services, with Supabase and Resend unchanged:

| Piece | AWS service | What it does |
| --- | --- | --- |
| Website | **S3** (file storage) | Holds the built React files |
| API | **Lambda** (code that runs per request) | Runs the Flask backend, only while someone uses it |
| Front door | **CloudFront** (global content network) | One address with HTTPS: pages come from S3, `/api/*` goes to Lambda |
| Domain | **Route 53** (DNS) + **ACM** (certificates) | Points floorpov.gg at CloudFront, with a free certificate |

Everything is described in code, so nothing is clicked together by hand except the one-time setup below:

- `aws/template.yaml`: the whole site (CloudFormation/SAM). Changing it and merging is how you change the AWS setup.
- `aws/github-deploy-role.yaml`: one-time setup; lets GitHub deploy, plus a budget alert.
- `.github/workflows/deploy-aws.yml`: on every merge to `main`, GitHub tests the code, deploys the template, uploads the website and clears CloudFront's cache.

Render keeps running the whole time. Nothing changes for visitors until the last step.

## One-time setup

### 1. Create the AWS account

1. Sign up at aws.amazon.com.
2. Turn on MFA (two-factor) for the root user: account menu (top right) → Security credentials.
3. In the top-right region menu, pick **US East (N. Virginia) us-east-1**. Use this region for everything here.

### 2. Let GitHub deploy (and set a budget alert)

1. Open **CloudFormation** → **Create stack** → **With new resources**.
2. Choose **Upload a template file** and pick `aws/github-deploy-role.yaml` from this repo.
3. Stack name: `floorpov-setup`. Fill in **BudgetEmail**. Leave the rest as is.
4. On the last page, tick "I acknowledge that AWS CloudFormation might create IAM resources", then **Submit**.
5. When it says `CREATE_COMPLETE`, open the **Outputs** tab and copy **DeployRoleArn**.

AWS emails you to confirm the budget alert address; click the link.

### 3. Create the rate-limit table in Supabase

Supabase → SQL Editor → New query → paste `backend/migrations/003_rate_limits.sql` → Run.

### 4. Give GitHub the settings

GitHub repo → Settings → Secrets and variables → Actions.

**Variables** tab:

| Name | Value |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | the DeployRoleArn from step 2 |
| `SUPABASE_URL` | `https://eckershozscyedwfswsy.supabase.co` |

**Secrets** tab:

| Name | Value |
| --- | --- |
| `SUPABASE_KEY` | same as `SUPABASE_KEY` in Render's backend environment |
| `SUPABASE_SERVICE_ROLE_KEY` | same as in Render's backend environment |
| `ORIGIN_SECRET` | 40+ random letters and digits from a password generator; nobody ever types it |

### 5. First deploy: the preview

1. The pull request that added this folder must be merged first; until then GitHub doesn't know the workflow. Then: GitHub → **Actions** → **Deploy to AWS** → **Run workflow** (on `main`).
2. It takes about 10 minutes the first time (CloudFront is slow to create).
3. When it's green, the run's summary shows the site address, like `https://d1234abcd.cloudfront.net`.
4. Supabase → Authentication → URL Configuration → **Redirect URLs**: add that address, so password-reset emails work on the preview.

Test the preview: run an analysis, sign in, save, share, open a saved report.

### 6. Move the domain to AWS (when the preview checks out)

The domain's DNS currently lives with your registrar or Render. These steps move it to Route 53 without downtime until the final switch.

1. **Route 53** → Hosted zones → **Create hosted zone** → `floorpov.gg`, public.
2. Copy **every** record from the current DNS provider into it, including email records (MX, and the TXT/CNAME records Resend gave you). Copy the website records too (`floorpov.gg` and `www`, pointing at Render), so the site keeps working during the move.
3. At the domain registrar, replace the nameservers with the four `ns-...` names in the hosted zone's NS record. This can take a few hours to spread.
4. GitHub variables: add `DOMAIN_NAME` = `floorpov.gg` and `HOSTED_ZONE_ID` = the hosted zone's ID (starts with `Z`). Run **Deploy to AWS** again. This creates the HTTPS certificate and attaches floorpov.gg to CloudFront; the site is still served by Render.
5. **The switch** (pick a quiet hour; about 2 minutes of downtime):
   1. In Route 53, delete the two website records you copied (`floorpov.gg` and `www.floorpov.gg`).
   2. Add the GitHub variable `POINT_DOMAIN_AT_AWS` = `true` and run **Deploy to AWS**.
6. After a week with no problems, delete the Render services. That's where the savings come from.

## Day to day

- **Deploying:** merge to `main`. The workflow deploys to AWS (and Render deploys too, until it's shut down).
- **Logs:** CloudWatch → Log groups → `/aws/lambda/floorpov-ApiFunction-...`.
- **Cost:** Billing → Bills. Expected: about $1/month (Route 53 zone $0.50; the rest is in the free tiers at this traffic).

## Why it's set up this way

- **No AWS keys in GitHub.** GitHub proves who it is to AWS (OpenID Connect) and gets keys that expire in an hour, only for `main`.
- **The API can only be reached through CloudFront.** Lambda gives the API a public address of its own; CloudFront sends a secret header (`ORIGIN_SECRET`) that the API checks.
- **Hourly limits count in Supabase.** Each concurrent request can run on its own copy of the API, so limits held in one copy's memory wouldn't add up.
- **Saves and shares are gzipped by the browser,** because Lambda refuses requests over 6 MB and a season's analysis is about 6 MB of JSON.
- **The analysis stream sends a "still working" line every 15 seconds,** because CloudFront drops a stream that's silent for 60.
