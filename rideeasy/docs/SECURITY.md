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

## 5. Payment Verification & Settlement
- Paystack secrets are server-side deployment secrets; checkout never accepts a client-provided amount, reference, or success status as authoritative.
- Webhook signatures are checked with HMAC-SHA512 and constant-time comparison. Both callbacks and webhooks then retrieve the transaction directly from Paystack and verify its reference, currency, amount, ride, and passenger.
- Payment settlement, ledger splits, reward awards, and in-app notices are written atomically. Unique payment references, one active/paid payment per ride, unique ledger shares, and one reward award per ride prevent duplicate checkouts and callback retries from duplicating balances or points.
- Payment checkout requires a transactional database. A configured but unavailable Turso database fails closed rather than silently switching to local SQLite. Use `libsql://`, `ws://`, or `wss://`; the HTTP-only Turso transport does not support the required transaction.
- Admin and driver amounts are ledger credits, not automatic transfers. Admins must confirm external mobile-money payouts before marking a ledger entry paid. The confirmation is protected by admin RBAC, a session-bound CSRF token, and an audit record.
- The Paystack merchant settlement number is not changed by the admin contact/reference setting; merchant settlement details remain controlled in Paystack.

## 6. Notifications and operational limits
- SMS provider requests use bounded connection/read timeouts. Unconfigured or failed SMS attempts are recorded for admin review and retry; payment settlement remains committed even when SMS delivery fails.
- External gateway latency and provider availability are outside RideEasy's control. The application targets prompt callback processing but cannot guarantee a 30-second end-to-end payment, transfer, or SMS SLA.
