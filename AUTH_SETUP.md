# Local authentication setup

The app uses one account and stores no users or passwords in a database. Set these environment variables before starting it:

```powershell
$env:APP_USERNAME = "admin"
$env:APP_PASSWORD_HASH = (python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('replace-with-a-strong-password'))")
$env:SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
python app.py
```

Set these variables again whenever you open a new PowerShell session, or configure them as persistent environment variables. If `APP_PASSWORD_HASH` is missing, the login page will show a setup error instead of accepting any password.

Use a long, unique password and replace the example immediately. Do not put the password, password hash, `SECRET_KEY`, or webhook URL in source control.

For HTTPS hosting, set `COOKIE_SECURE=1`. Keep `FLASK_DEBUG` unset in production. The login rate limiter is in memory, so restarting the process clears it and multiple workers have separate limits.
