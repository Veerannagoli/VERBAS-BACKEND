# VERBAS API security

Included:
- Production SECRET_KEY enforcement
- Secure HttpOnly SameSite=None cookies for Netlify → Render
- CSRF protection
- Exact-origin CORS with credentials
- Login throttling
- Password hashing
- Role-based authorization
- Parameterized SQL
- Input validation
- Request-size limit
- Security headers and HSTS
- Debug disabled by default
- Generic API errors
- No frontend files in this package
- No `.env` or test employee records
- Non-destructive database initialization
