# Oracle Always Free backend setup

This is a console-based setup for the existing Vercel website. Nothing in this
repository creates an Oracle account, accepts terms, provisions infrastructure,
or upgrades billing. The deployment remains a single-server beta.

## 1. Account and resource choices

Create an account at https://www.oracle.com/cloud/free/. Complete signup and
card verification yourself. Choose your **home region** carefully: free compute
must be provisioned there. In the Console, confirm the Always Free eligibility
and your existing resource usage before creating anything.

Use these conservative choices for a new, otherwise unused tenancy:

| Setting | Choice |
| --- | --- |
| Compartment | Create `production-rag` |
| Instance | `production-rag-api` |
| Shape | Ampere `VM.Standard.A1.Flex` |
| Compute | **2 OCPUs, 12 GB RAM total**, including any other A1 instances |
| Image | Oracle-provided Canonical Ubuntu 24.04, **aarch64 / ARM64** |
| Boot volume | **50 GB**, default Balanced performance |
| Network | One VCN, one public subnet, one internet gateway |
| Public IP | Automatically assigned ephemeral IPv4 |
| SSH | Your public key; keep the private key on your computer |
| Object bucket | Private `raw-docs`, Standard tier, in the same home region |

These choices use part of the documented 200 GB combined boot/block allowance.
Keep the initial sample corpus below 1 GB; current free storage and request
allowances are shared across the tenancy and vary with account/trial status.
Check the [current Always Free rules](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
rather than older tutorials showing 4 OCPUs / 24 GB.

Choose platform images, not paid Marketplace images. Leave optional load
balancers, NAT gateways, GPUs, paid monitoring, extra volumes, replication, and
automatic storage tiering out of this initial setup. Trial credits are temporary;
an account budget notification is not a spending cap. If eligibility or cost is
unclear, stop before creating the resource. If A1 capacity is unavailable, try
another availability domain in the home region or wait; do not substitute a paid
shape or upgrade the account to bypass the capacity error.

The default 8B model's memory use and CPU latency on this VM are unmeasured.
ARM container CI confirms the software builds and imports; it does not establish
that answers fit the web gateway deadline. Keep the showcase available if the
actual machine fails the checks in section 5.

## 2. Network and HTTPS

For the public subnet, use a route to the internet gateway for `0.0.0.0/0`.
Review all attached security lists and network security groups: OCI allow rules
are additive. Limit inbound TCP to:

| Destination port | Source |
| --- | --- |
| 22 | Your current public IPv4 address as `/32` |
| 80 | `0.0.0.0/0` for HTTP-to-HTTPS redirects and certificate issuance |
| 443 | `0.0.0.0/0` for the authenticated HTTPS API |

Retain required ICMP path-MTU handling. Allow outbound traffic for DNS, Ubuntu
updates, model/image downloads, Clerk JWKS, and object storage. Do not add public
rules for 5432, 6379, 6333/6334, 8000, or 11434. The Compose stack publishes only
the HTTPS gateway; data stores and Ollama stay on its private Docker network.

Create a DNS A record for a backend hostname pointing to the instance's public
IP. A DNS hostname you can manage is required by Caddy. A free DNS subdomain can
be used for a test API; this does not satisfy Clerk's separate production-domain
requirements. An ephemeral IP can change after a stopped instance restarts, so
update DNS if needed.

Ubuntu images can also have host firewall rules. Inspect them and preserve SSH
and platform rules. Add only the needed web ports, following
[Oracle's host firewall guidance](https://blogs.oracle.com/developers/enabling-network-traffic-to-ubuntu-images-in-oracle-cloud-infrastructure).
Do not flush the firewall or replace its policy with allow-all. Docker-published
ports can bypass some host firewall frontends; the OCI ingress rules and the
Compose port allowlist must remain restrictive.

## 3. Private object storage and scoped credentials

Create the `raw-docs` bucket as an administrator in the `production-rag`
compartment. Keep public access disabled, use Standard storage and Oracle-managed
encryption, and disable versioning and auto-tiering for this small beta. Do not
create preauthenticated public links or share administrator credentials with
the application.

Create a dedicated user and group, for example `production-rag-storage`, in your
identity domain. The user must not belong to administrator groups. Grant the
group bucket metadata reads and object operations only for `raw-docs`. For a
domain named `Default`, these example policy statements are:

```text
Allow group Default/production-rag-storage to read buckets in compartment production-rag where target.bucket.name='raw-docs'
Allow group Default/production-rag-storage to manage objects in compartment production-rag where all {target.bucket.name='raw-docs', any {request.permission='OBJECT_INSPECT', request.permission='OBJECT_READ', request.permission='OBJECT_CREATE', request.permission='OBJECT_OVERWRITE', request.permission='OBJECT_DELETE'}}
```

Replace the identity domain, group, compartment, and bucket names if different.
Review inherited memberships too: this policy cannot remove broader access
granted elsewhere. See [IAM syntax](https://docs.oracle.com/en-us/iaas/Content/Identity/policieshow/Policy_Basics.htm)
and [Object Storage permissions](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/objectstoragepolicyreference.htm).

Generate a **Customer Secret Key** for the dedicated storage user. Its access
key and secret key are S3 credentials; they are different from an OCI API signing
key or the login password. Save them directly into the server configuration,
not GitHub, Vercel, or chat. Record the Object Storage namespace and region.

Map them to the application's existing settings:

```dotenv
MINIO_ENDPOINT=<namespace>.compat.objectstorage.<home-region>.oraclecloud.com
MINIO_REGION=<home-region>
MINIO_ROOT_USER=<Customer Secret Key access key>
MINIO_ROOT_PASSWORD=<Customer Secret Key secret key>
MINIO_BUCKET=raw-docs
```

The legacy variable names do not imply administrator/root credentials. Use only
the endpoint hostname, without `https://`, `/n/`, or the bucket path. The server
stack sets `MINIO_SECURE=true`. The explicit region signs requests for OCI and
avoids automatic bucket-location discovery. Minio's client uses path-style
URLs for this custom endpoint. See [OCI S3 compatibility](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/s3compatibleapi.htm).

## 4. Prepare Ubuntu and the application

Connect as the platform image's `ubuntu` user using your own private key. Run
`uname -m` and confirm `aarch64`. Install Docker Engine and the Compose plugin
using [Docker's Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/),
which support ARM64. Install Git and OpenSSL from Ubuntu's repositories as needed.
Use `sudo docker ...` unless you deliberately grant the login user Docker access;
membership in the Docker group effectively grants root access.

Clone the repository and prepare the ignored configuration:

```bash
git clone https://github.com/The-Great-Aeochs/production-rag.git
cd production-rag
cp deploy/server.env.example deploy/server.env
chmod 600 deploy/server.env
mkdir -p deploy/documents
```

Edit `deploy/server.env` on the server. Fill in the backend DNS hostname,
certificate contact, S3 mapping above, Clerk issuer, and independent application
secrets. Generate each application secret separately with `openssl rand -hex 32`.
The Clerk issuer requires creating the Clerk application first; follow
[beta-launch.md](beta-launch.md#1-create-the-clerk-application). Leave the public
demo disabled. Use a unique `RAG_IMAGE` release tag based on the deployed Git SHA.

Define the deployment helper and build the application:

```bash
dc() { sudo docker compose --env-file deploy/server.env -f deploy/compose.yaml "$@"; }
dc --profile release config --quiet
dc build api
dc run --rm --no-deps release python -m scripts.check_object_store
```

The object-store check makes real S3 requests: it verifies the bucket exists,
writes a tiny object under `_deployment-check/<uuid>.txt`, reads the bytes back,
and deletes only that test key. It never creates buckets or deletes source
documents. A failed cleanup can leave a test object; remove only that prefix if
needed. A successful run confirms real connectivity and basic S3 compatibility,
not durability or application answer quality.

Continue the migrate, model pull, seed, and startup commands in
[beta-launch.md](beta-launch.md#2-prepare-the-server), using the sudo-enabled `dc`
helper above. Do not start API replicas before migrations. Do not publish a
partially configured backend to Vercel.

## 5. Launch gate and recovery

After seed ingestion completes, require `/health/ready` to return HTTP 200.
Set Vercel's `RAG_API_URL` to the backend's HTTPS origin and redeploy, then run
`python -m scripts.check_deployment` with the website and backend URLs as shown
in the beta guide. Test real sign-in and separate role accounts, then measure
uncached cited answers on representative documents. Keep the existing deadlines
and do not call a slow or incomplete stream a successful answer.

Check `dc stats --no-stream`, disk capacity, worker logs, and model availability
during the test. Keep off-host backups of Postgres, source files, and configuration;
the bucket alone cannot restore memberships, jobs, and document publication state.
Exercise restoration before adding private documents. Free instances can be
reclaimed, and this server has no failover. See [production.md](production.md).

No account credentials, cloud resources, real S3 test results, or measured VM
performance are included with this setup. Provision and verify them in your own
account before enabling the live demo.
