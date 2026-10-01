# VERBAS Render Backend — API ONLY

**Backend only. No `templates/` and no `static/` folders.**

Architecture:

Netlify frontend → Render Flask API → Aiven MySQL

### API

GET `/api/health`
GET `/api/auth/csrf`
POST `/api/auth/login`
POST `/api/auth/logout`
GET `/api/auth/me`

GET `/api/employee/dashboard`
POST `/api/employee/check-in`
POST `/api/employee/check-out`
POST `/api/employee/work`

GET `/api/admin/dashboard`
GET `/api/admin/employees`
POST `/api/admin/employees`
PATCH `/api/admin/employees/<id>/toggle`
POST `/api/admin/attendance/generate`
GET `/api/admin/attendance/current`
POST `/api/admin/notes`
GET `/api/admin/notes`

### Render

Build:
`pip install -r requirements.txt`

Start:
`gunicorn app:app`

Health:
`/api/health`

Set the environment variables in `.env.example` in Render.

### Fresh production start

The API creates missing tables only. It does not create employee test records.
The optional admin is created from `DEFAULT_ADMIN_*` only if that admin email does not exist.

Use a fresh production MySQL database for the cleanest first deployment.

### Netlify

The frontend must use the Render API URL and send credentials with requests.
Set `CORS_ORIGINS` to the exact frontend origin(s).
