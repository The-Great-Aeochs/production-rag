# Launch the deployed website with login and a backend

The showcase is at https://production-rag-pi.vercel.app. Login and live inference
are not enabled until account configuration and backend verification are done.
This guide prepares a small beta; it does not establish capacity or availability.

## Budget and accounts

The website can stay on Vercel Hobby for personal, non-commercial use within its
limits. The backend needs a server, persistent storage, and model memory. A free
subscription alone does not provision those resources.

[Oracle Always Free](https://www.oracle.com/cloud/free/) is one possible server
and object-storage option. Signup requires card verification; capacity and
[current allowances](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
must be checked in the account before creating anything. Select only resources
marked Always Free; trial credits are temporary. Idle instances can be reclaimed.
No Oracle account or resources are included or automatically created here.

Do not choose a small free web-service instance just because it accepts a
Dockerfile. Both API and worker load embedding weights, and Ollama also needs
memory for the generation model. CPU latency and memory on a free VM have not
been measured. If the available machine cannot pass readiness and answer within
the existing 60-second generation / 70-second web gateway deadlines, retain the
showcase until capacity is available. Smaller models require separate quality
evaluation; do not silently change the model or extend timeouts to hide failures.

## 1. Create the Clerk application

1. Open https://dashboard.clerk.com and create an application named
   `Production RAG`. Start with email sign-in to avoid separate OAuth setup.
2. Use the **Development** instance for initial testing on the existing
   `production-rag-pi.vercel.app` URL. This is development authentication, not a
   production identity deployment. Use test accounts and public sample documents.
3. In JWT templates, create `production-rag`, leave standard issuer, subject,
   issued-at, and expiry claims intact, use RS256 signing and a 60-second lifetime,
   and add the custom claim `{"aud":"production-rag"}`. Do not add workspace
   roles. Check an issued token for the exact `iss` and `azp` before configuring
   the backend allowlist.
4. Add these values directly in **Vercel → production-rag → Settings →
   Environment Variables** for the deployment you are testing, then redeploy:

   | Variable | Value |
   | --- | --- |
   | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Development `pk_test_...` key |
   | `CLERK_SECRET_KEY` | Matching `sk_test_...` key; server only |
   | `CLERK_JWT_TEMPLATE` | `production-rag` |
   | `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | `/sign-in` |
   | `NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL` | `/workspace` |
   | `SITE_URL` | `https://production-rag-pi.vercel.app` |

Do not paste secrets in chat or commit them. Login can be tested before setting
`RAG_API_URL`; workspace API calls will report that the backend is not connected.

For a public production identity deployment, use a domain you control, create
the Clerk Production instance, configure its DNS, and replace both Clerk keys,
JWT issuer, and allowed origins together. Development users and production
users belong to separate instances. Clerk explicitly does not support
`*.vercel.app` as the domain of a production instance. See
[Clerk on Vercel](https://clerk.com/docs/guides/development/deployment/vercel).

## 2. Prepare the server

`deploy/compose.yaml` is a separate single-server stack. It does not override the
local development Compose file. It runs API, worker, Postgres, Redis, Qdrant,
Ollama, and a Caddy HTTPS gateway. Only ports 80/443 are published. Database and
model transports are unencrypted inside this trusted, single-host Docker bridge;
use encrypted transports and network policies when moving services across hosts.
An external supported S3-compatible store is required for raw documents.

On a Linux server with Docker Engine and Compose installed:

```bash
git clone https://github.com/The-Great-Aeochs/production-rag.git
cd production-rag
cp deploy/server.env.example deploy/server.env
chmod 600 deploy/server.env
mkdir -p deploy/documents
```

Edit `deploy/server.env` on the server:

- Set `API_DOMAIN` to a DNS hostname pointing at the server. Permit inbound
  80/443 for certificates and HTTPS, and restrict SSH to your own addresses.
  Do not expose Postgres, Redis, Qdrant, Ollama, or port 8000 through host networking.
- Generate each independent secret with `openssl rand -hex 32`. Use hex for the
  Redis password so embedding it in the internal Redis URL needs no escaping.
- Copy the exact Clerk issuer into `JWT_ISSUER`. Set
  `JWT_AUTHORIZED_PARTIES=["https://production-rag-pi.vercel.app"]` after verifying
  the template's `azp`. Keep `API_KEYS={}`; workspace roles come from Postgres.
- Precreate a private `raw-docs` bucket. Enter its scoped S3 access key, secret,
  and hostname into the legacy `MINIO_*` variables. The stack enforces HTTPS.
  [OCI's S3-compatible API](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/s3compatibleapi.htm)
  is one option if available in the account; test real put/get/delete operations
  before relying on it. Restrict the credential to the bucket, and never use
  an administrator credential.
- Keep `DEMO_ENABLED=false` until ingestion, quotas, and readiness are verified.
  Set `RAG_IMAGE` to a unique release tag, such as `production-rag:<git-sha>`.

From the repository root, define this shell helper for the remaining commands:

```bash
dc() { docker compose --env-file deploy/server.env -f deploy/compose.yaml "$@"; }
dc --profile release config --quiet
dc build api
dc up -d postgres redis qdrant ollama
dc run --rm release
dc exec ollama sh -c 'ollama pull "$1"' sh \
  'hf.co/unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL'
```

If `OLLAMA_MODEL` was explicitly changed, pull that exact model instead and
evaluate its answers before launch. No paid cloud inference is enabled.

Seed the curated public corpus using a one-off writable source mount; normal API
and worker source mounts stay read-only. On this fresh source directory, grant
write access to the non-root container UID before seeding:

```bash
sudo chown 10001:10001 deploy/documents
dc run --rm --no-deps -v "$PWD/deploy/documents:/documents" release \
  python -m scripts.seed_demo
dc up -d worker api gateway
dc logs --tail=50 worker
curl --fail https://YOUR_API_DOMAIN/health/ready
```

Wait for the seed job to complete; Qdrant readiness stays false before its
collection exists. Model downloads and first warmup can take time. Free-VM
performance is not certified by a successful container build.

## 3. Connect Vercel and verify

Set `RAG_API_URL=https://YOUR_API_DOMAIN` in Vercel and redeploy. The browser talks
to the Next.js gateway, which forwards the signed-in Clerk JWT to FastAPI. No
backend admin credential goes into Vercel, and browser-to-backend CORS is not
needed for this flow.

Run the automated HTTP checks from an environment with the Python dependencies:

```bash
python -m scripts.check_deployment \
  --site-url https://production-rag-pi.vercel.app \
  --api-url https://YOUR_API_DOMAIN
```

The command fails on readiness errors, redirects, unconfigured JWT/gateway
authentication, anonymous access, or accepted cross-origin mutations. It sends no
real credentials, requests no model generation, and uses an invalid body for the
cross-origin probe. `--json` provides a machine-readable report. To verify only
the current showcase, replace `--api-url ...` with `--showcase-only`.

Then verify the actual user flow manually; the HTTP checker cannot prove it:

1. Sign in, open `/workspace`, and create a test workspace. The workspace will
   initially have no documents; the public demo corpus is separate.
2. An operator places trusted files under `deploy/documents/<workspace-id>/`.
   An editor/admin refreshes that source and waits for ingestion to finish.
3. Ask a real question and inspect its citations. Check insufficient-context
   questions and malicious text in retrieved documents with public test data.
4. Use separate outsider/member/editor/admin test accounts to verify denied
   reads and mutations, workspace switching, and revoked membership. Do not
   treat successful login alone as proof of authorization.
5. Only then enable the capped public demo following [website.md](website.md).

Before admitting private documents, move to production identity, verify external
S3/Qdrant integration, and exercise the backup/restore process in
[production.md](production.md). Docker volumes survive container replacement,
but a lost or reclaimed server can lose them. Keep encrypted, off-host backups
of Postgres, sources/object storage, and the release configuration.

## Subsequent releases

Record the deployed Git SHA and image tag. Back up the stores and preserve the
previous image/configuration before pulling a new `main`. For this small beta,
use a maintenance window: stop `api`, `worker`, and `gateway`, build the new image,
run `dc run --rm release` once, then restart the services and run the launch
checks. Never restore an old image across an incompatible schema; follow the
rollback rules in the operations guide. Do not use `down --volumes` during a
release or cleanup.
