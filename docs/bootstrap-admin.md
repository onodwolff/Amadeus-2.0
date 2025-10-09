# Bootstrap administrator account

The FastAPI gateway seeds an administrator account the first time the application boots so you always have a privileged user.
The behaviour is controlled entirely through environment variables and is safe to run repeatedly because the same account is
reconciled on every startup.

## Configure credentials

Set the following variables (for local development you can edit the `.env` file at the repository root):

```ini
AUTH__ADMIN_EMAIL=volkov.zheka@gmail.com
AUTH__ADMIN_PASSWORD=volkov650
```

Only the first boot after the database is created needs these values, but keeping them around enables an automatic password
reset during future deployments.

## What happens on startup

When the gateway process starts, it calls `_ensure_admin_user()` during application initialisation. The routine:

1. Normalises the configured email to lowercase and searches for an existing record.
2. Generates a unique username from the email prefix (`volkov.zheka`, `volkov.zheka2`, …) if the user is new.
3. Hashes the configured password with Argon2id before storing it.
4. Sets the account role to administrator, enables the `is_admin` flag, and marks the email as verified.
5. Disables multi-factor authentication so the account is immediately usable.

If the account already exists, the email, password hash, and admin flags are refreshed instead of creating a duplicate user.

## Why the routine only runs once

The `_ensure_admin_user()` hook executes during application startup and reads the administrator credentials exclusively from
environment variables. When the database is empty the first boot creates the user; subsequent boots simply find the existing
record and update the password hash if the environment variables are still present. In other words, only someone with access
to the deployment environment can trigger the bootstrap. Regular UI or API users cannot invoke the routine again, which makes
the initial administrator creation effectively a one-time action.

You can remove the variables after the first boot if you prefer. Leaving them in place is also safe—they will only rotate the
password on each deploy, which can be useful for a controlled reset.

## No default users without bootstrap

Until the bootstrap routine runs, the database contains no users at all. Requests to the settings endpoints (or any other
protected resource) return the `"No user account configured"` error, confirming that the system starts in a locked-down state.
Defining the environment variables and running the migrations ensures the administrator account exists before anyone interacts
with the application.

## Result

With the variables defined, deploying the stack automatically produces a single administrator account. Removing the variables
after the initial boot is safe—the application will keep using the previously created user. Keeping them is also fine if you
want to rotate the password on every deployment.
