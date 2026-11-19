# Helpdesk IT — operational handoff

Flask/SQLAlchemy ticketing application with an Indonesian UI, UTC storage and Asia/Jakarta (WIB) display. Production target: MySQL 8.0, Gunicorn and Docker Compose. Web binds only to 127.0.0.1:5017; MySQL has no published host port.

## Current deployment and verification

The application is deployed with Docker Compose and MySQL 8.0.46. Both web and database passed health checks; `/login` returned HTTP 200 and `/health` returned `{"status":"ok"}`. The application database was initialized using the shipped migrations and starter categories. The initial admin was created using the Flask CLI. Secrets are stored only in ignored mode-0600 `.env` and `.local-credentials`; never share their contents in logs.

Latest password-management regression: **44 passed on isolated MySQL in 84.38s** (40 non-fatal warnings: WTForms deprecations and pytest cache permissions). Chromium browser verification of employee/agent/admin password changes, old-password rejection, new-password login, authorization, validation, CSRF and responsive layout passed with zero page errors. Evidence: `verification/password-change/report.md`, `results.json`, `desktop.png`, `mobile.png`. Browser changes were limited to `helpdesk_test`, not live accounts.

Latest dashboard/role/priority regression: **31 passed on MySQL in 72.77s**, including the original workflow and concurrent claim tests. The initial new tmpfs test run applied migrations and passed 31 tests in 63.31s; a follow-up run also checked saved priority labels across employee/IT/admin lists. Local SQLite suite: 31 passed in 81.25s. MySQL emitted 35 WTForms deprecation warnings and one pytest cache-permission warning, none fatal. The isolated test database was stopped; live web/MySQL remain healthy.

Real headless Chromium acceptance passed using `scripts/browser_acceptance.py`: admin creates accounts; employee creates a ticket; agent claims/replies; employee sees the reply; agent progresses, resolves, reopens and closes. Second-employee direct GET/reply and unassigned-agent updates returned 403; closed replies returned 409. No horizontal overflow at 390px and no JavaScript page errors. Evidence: `verification/browser-results.json`, `employee-reply.png`, `closed-ticket.png`, `mobile-ticket.png`. This run left a closed acceptance ticket and identifiable QA accounts in the application database. The browser tool's snap Chromium could not start, so the successful browser run used Playwright-managed Chromium instead.

### Private laptop access

On a laptop able to SSH to this server on the LAN:

    ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:5017:127.0.0.1:5017 tpang@192.168.0.121

Then open **http://127.0.0.1:5017/login** on the laptop. A verified server Tailscale address is `100.104.29.63`, usable instead of the LAN address when the laptop has tailnet access. Laptop SSH connectivity itself was not tested. Do not publish 5017 on 0.0.0.0 or configure a public reverse proxy. Initial login credentials can be read privately on the server from `.local-credentials`.

## Secrets and configuration

.env.example exists and contains placeholders only, not real secrets. .env, .local-credentials, instance and .venv are excluded from source/image context by the supplied ignore files. There are no default production login credentials.

After obtaining permission to provision the deployment, create a private .env from .env.example yourself (chmod 600). Supply three independently generated values:

- SECRET_KEY: at least 32 random bytes represented by 64 hexadecimal characters; used for sessions/CSRF. Rotation invalidates sessions.
- DB_PASSWORD: independent URL-safe hexadecimal password for the helpdesk MySQL account.
- DB_ROOT_PASSWORD: a different random hexadecimal MySQL root password.

For example, run `openssl rand -hex 32` separately for each value. Do not paste generated secrets into source control, tickets, screenshots or logs. Use hexadecimal values so embedding the application password in a URL requires no additional escaping.

Compose must resolve the web DATABASE_URL to `mysql+pymysql://helpdesk:<DB_PASSWORD>@db/helpdesk?charset=utf8mb4`. Before startup, privately inspect the rendered configuration and verify that its password matches MYSQL_PASSWORD, not a literal placeholder. The tests' two database URLs must use tester's isolated-test-only password and the test-db host. Avoid sharing rendered configuration because it exposes secrets. Compose validation and image build completed successfully.

Outside Compose the application reads SECRET_KEY and DATABASE_URL from the process environment; .env is not automatically loaded by application code. Always set DATABASE_URL explicitly: its development fallback is ephemeral SQLite, not persistent MySQL. Missing SECRET_KEY prevents normal application startup.

## Docker deployment commands

Prerequisites: Docker Engine with Compose v2, permission to use Docker, configured private .env, and available localhost port 5017. From this directory:

    docker compose config --quiet
    docker compose build web
    docker compose up -d db
    docker compose run --rm web flask --app helpdesk db upgrade
    docker compose run --rm web flask --app helpdesk seed-categories
    docker compose run --rm web flask --app helpdesk create-admin
    docker compose up -d web
    docker compose ps
    docker compose logs --tail=100 db web
    curl --fail http://127.0.0.1:5017/health

create-admin prompts for email, name and a hidden, confirmed password (12–128 characters). Prefer the prompt to --password, which leaks into shell/process history. Duplicate emails are rejected. Log in as this admin and create employees/IT agents in Pengguna. seed-categories is idempotent and installs Network/Jaringan, Hardware/Perangkat Keras, Accounts and Access/Akun dan Akses and Applications/Aplikasi. Account creation is not part of category seeding.

The image's normal entrypoint also runs `flask db upgrade` before Gunicorn. Explicit migration above makes initial setup failures easier to diagnose. Health checks test database connectivity, not schema completeness or authorization.

Routine operations:

    docker compose logs -f web
    docker compose restart web
    docker compose exec web flask --app helpdesk db current
    docker compose exec web flask --app helpdesk db history
    docker compose exec web flask --app helpdesk db upgrade
    docker compose up -d --build web
    docker compose stop
    docker compose down

`down` preserves mysql_data. Do NOT run `docker compose down -v` on a deployment you need: it destroys the database volume. Back up MySQL and verify restoration before upgrades. Changing .env passwords does not change accounts in an already initialized MySQL volume; coordinate ALTER USER and service configuration instead of deleting the volume.

## Migrations

Schema changes are Alembic/Flask-Migrate migrations under migrations/. Do not use db.create_all as a migration substitute. Apply `flask --app helpdesk db upgrade` to the intended database before use. Review generated migration scripts and test against a disposable database before deployment; downgrades may discard data. Backups/restore drills and migration rollback remain operator responsibilities.

For a new local SQLite test database (not needed for the already migrated database used above):

    SECRET_KEY=local-migration-only DATABASE_URL=sqlite:///helpdesk_test .venv/bin/python -m flask --app helpdesk db upgrade
    TEST_DATABASE_URL=sqlite:///helpdesk_test .venv/bin/python -m pytest -q

Relative Flask SQLite paths resolve under instance/. Never point tests at a deployment database. The fixture requires the database name helpdesk_test and DELETES ALL DATA in its application tables before each test; the name check is not a substitute for isolated credentials and host selection.

## Isolated MySQL tests

The test profile supplies a separate MySQL test-db with helpdesk_test, separate tester credentials and tmpfs storage. It does not use mysql_data. Fixed isolated-test-only/isolated-root-only credentials are disposable test fixtures, not production secrets. No test database port is published.

After obtaining Docker permission and supplying Compose's required .env values:

    docker compose --profile test build tests
    docker compose --profile test up -d test-db
    docker compose --profile test run --rm tests
    docker compose --profile test stop test-db
    docker compose --profile test rm -f test-db

The tests service waits for test-db health and executes real Alembic upgrades followed by pytest. A failing command must block acceptance. Do not replace these URLs with the production database URL. For an independently provisioned disposable MySQL database named helpdesk_test, set both DATABASE_URL (for migration) and TEST_DATABASE_URL (for pytest) to that isolated database, migrate first, then run tests. SQLite cannot validate MySQL row locks, deadlocks, collation or concurrent migration behavior.

## Application behavior

- Employees land on `/` (Tiket Saya), with scoped counts, search, filters and 20-row pagination over their own tickets only. `/tickets` is reserved for IT/admin and returns 403 to employees; IT/admin login and root lead to that queue. Navigation is role-specific.
- New tickets start Terbuka and unassigned. Employees choose Rendah/Normal/Tinggi initially; omitted priority defaults to Normal, invalid values return an Indonesian validation error, and selected values survive other validation failures. Subsequent priority changes remain assigned-agent/admin only with activity history.
- IT agents can inspect the queue and atomically claim unassigned, non-closed tickets. Only the assigned agent or an admin can operate a ticket.
- Workflow: Terbuka → Diproses → Terselesaikan → Ditutup; Terselesaikan can return to Diproses. Closed tickets reject replies and priority changes.
- Admins manage users/categories and assign active IT agents. Active work must be reassigned before an agent can be deactivated/demoted.
- Admin password management: open **Pengguna → Ganti Password** on any employee, IT agent, or administrator card (including your own). Confirm the currently signed-in administrator's password, enter a new password of 12–128 characters and repeat it. Passwords are hashed; routes are admin-only and CSRF-protected. Successful changes show an Indonesian confirmation. No email reset link or notification is sent; communicate reset passwords through a secure channel. Existing authenticated sessions are not revoked by a password change. CLI-created `.local-credentials` is only a bootstrap record and is not automatically updated when changing the administrator password in the UI.
- Password browser regression: after the isolated MySQL tests pass, run `docker compose --profile test run --rm --no-deps -d --name web-ticketing-password-browser -p 127.0.0.1:5018:8000 tests gunicorn --bind 0.0.0.0:8000 'helpdesk:create_app()'`, then `.venv/bin/python scripts/browser_password_change.py`. Requires a Playwright Chromium install in the local virtualenv and the standard pytest fixture accounts in `helpdesk_test`. The script changes only test passwords. Stop the disposable browser container with `docker stop web-ticketing-password-browser` before stopping test-db. Never redirect it to the live service.
- Replies and actor/timestamp activity histories are retained. Activity status/priority codes are translated into Indonesian on display, including historical update events. User-provided text remains escaped.

## Deferred acceptance and hardening

The MySQL suite, fresh-database migrations, Compose build/startup/health and real-browser workflow were verified as detailed above. Still unverified: laptop-side SSH/browser connectivity, backup restoration, load testing, broader accessibility audits, and close-versus-reply concurrency under stress.

Internet-facing deployment needs a reviewed TLS reverse proxy, trusted proxy configuration, secure session-cookie configuration (Secure is not currently enabled), authentication rate limiting, monitoring, backups and secret rotation procedures. Current scope does not provide email-based password recovery/self-registration, SSO, email notifications, attachments, SLA/escalation automation or external integrations. Load testing and operational recovery are deferred.
