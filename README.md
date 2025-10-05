# Amadeus 2.0

## Frontend development

Run frontend npm scripts from the `frontend/amadeus-ui` directory so the Angular CLI can find the workspace configuration. For example:

```bash
cd frontend/amadeus-ui
npm run start
```

Alternatively, you can run commands from the repository root using `npm --prefix frontend/amadeus-ui <command>`:

```bash
npm --prefix frontend/amadeus-ui run lint
```

This prevents "missing package.json" errors that occur when running the scripts from the wrong folder.
