# Developer Onboarding

## Repository access

Request access to the GitHub organization "andina-logistica" with a ticket
in the "Access" category. You will be added to the team of your squad;
write access to the main repositories is granted after your first merged
pull request.

## Local environment

Install Node.js 20 LTS and Docker Desktop (package pkg_docker from the
Software Portal). Clone the repository and run `docker compose up` to start
Postgres, Redis and the API locally. Seed data is loaded with
`npm run db:seed`. The API listens on port 3000 and the frontend on 5173.

## Code review rules

Every pull request needs one approval from a code owner and green CI.
Pull requests larger than 400 changed lines must be split unless the
reviewer agrees otherwise. Never push directly to main.

## Secrets in development

Development secrets live in the team vault in 1Password, never in the
repository. Copy .env.example to .env and fill it from the vault. A secret
committed by mistake must be rotated immediately, even if the commit was
reverted.
