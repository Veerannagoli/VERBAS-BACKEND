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


## Aiven MySQL TLS (required)

This backend verifies the Aiven MySQL server certificate. Aiven documents that its MySQL service supports certificate verification using the project CA certificate. Download the CA certificate from your Aiven MySQL service's **Overview → Connection information → CA certificate**.

In Render, open **Environment → Secret Files → Add Secret File** and create:

- **Filename:** `aiven-ca.pem`
- **Contents:** paste the complete PEM certificate from Aiven

Render makes the file available at `/etc/secrets/aiven-ca.pem`. The backend reads that file and enables `ssl_ca`, `ssl_verify_cert`, and `ssl_verify_identity` in MySQL Connector/Python.

Do not commit the CA certificate or database password to the repository. Render supports secret files for runtime credentials/certificates.
