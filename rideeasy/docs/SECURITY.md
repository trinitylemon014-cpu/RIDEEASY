# RideEasy Security Architecture & Hardening Guide
**Emtrixz Technology Company**

## 1. Authentication & Password Security
- **Algorithm**: Passwords are cryptographically hashed using PBKDF2 with SHA-256 (via `werkzeug.security.generate_password_hash` with random salt).
- **Storage**: Plaintext passwords are never logged, cached, or written to disk.
- **Session Security**: Session cookies are configured with:
  - `SESSION_COOKIE_HTTPONLY = True` (prevents XSS access)
  - `SESSION_COOKIE_SAMESITE = 'Lax'` (mitigates CSRF)
  - `SESSION_COOKIE_SECURE = True` in production (enforces HTTPS)

## 2. Server-Side Role-Based Access Control (RBAC)
Security is never enforced merely by hiding UI buttons. Every protected route enforces `@login_required` and `@role_required(*roles)`.
- If a passenger attempts to access `/driver/*`, `/school/*`, or `/admin/*`, the server terminates the request with HTTP `403 Forbidden`.
- Travel companies can only access flight requests explicitly assigned to their company ID.
- Schools can only access bookings belonging to their school account ID.

## 3. SQL Injection Prevention
All database queries use parameterized SQL arguments (`?` placeholders in SQLite and libSQL). Dynamic query concatenation is strictly prohibited.

## 4. Audit Logging
High-privilege actions (driver verification, school vehicle assignments, quotation approvals, booking PNR registrations) are automatically written to `audit_logs` with the operator's user ID, IP address, and timestamp.
