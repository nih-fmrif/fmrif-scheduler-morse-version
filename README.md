# Scheduler app

## Documentation
- [Project Documentation](docs/README.md)

## Human Quickstart
1. Generate local `.env`:
   `bash setup-dotenv.sh`
2. Start local services:
   - clean start: `bash run-compose.sh --no-app`
   - reuse existing data: `bash run-compose.sh --no-app --resume`
3. Run the app (optional):
   `pixi run serve`
4. Run tests:
   - `pixi run test-unit`
   - `pixi run test-routes`
   - `pixi run test-integration-ci`

## Notes
- Use `run-compose.sh` for containerized startup; direct `docker compose` is not supported in this workflow.
- App/bootstrap DB settings come from `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`.
- For setup details, see [docs/containerized-postgres.md](docs/containerized-postgres.md) and [docs/testing-guide.md](docs/testing-guide.md).
