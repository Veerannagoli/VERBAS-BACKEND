# VERBAS API — Render

1. Push this folder to GitHub.
2. Render → New Web Service.
3. Build: `pip install -r requirements.txt`
4. Start: `gunicorn app:app`
5. Health check: `/api/health`
6. Add the `.env.example` values to Render.
7. Enter your Aiven MySQL host, port, user, password and database.
8. Set `CORS_ORIGINS` to your Netlify/custom frontend URL.
9. Deploy.
10. Test `https://YOUR-SERVICE.onrender.com/api/health`.

Do not upload `.env` to GitHub.
