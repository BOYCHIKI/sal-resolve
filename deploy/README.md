# Deploying SAL on one server

Everything runs from `deploy/docker-compose.yml`: PostgreSQL 16, the API, the worker, the web, and Caddy, which gets
and renews the HTTPS certificate on its own. Only ports 80 and 443 are published.

Tested target: an Ubuntu 24.04 VM (ARM or x86) with Docker installed.

```bash
git clone https://github.com/BOYCHIKI/sal-resolve.git && cd sal-resolve
cp deploy/.env.example deploy/.env      # fill in: domain, random passwords and token, OpenAI key
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

- No domain of your own? Use the server's IP through sslip.io, e.g. `129-150-10-20.sslip.io`.
- The first start creates the database roles with the passwords from `deploy/.env`, runs the migrations, then starts
  the API and the worker. Uploaded documents live in the `storage` volume, shared by the API and the worker.
- To add a seller login to a business, run `docker compose -f deploy/docker-compose.yml exec api python -m app.accounts
  add-user you@example.com` and type the password when asked.
- Update: `git pull`, then the same `up -d --build`.
