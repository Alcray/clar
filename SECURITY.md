# Security policy

Report a vulnerability privately through this repository's GitHub **Security → Report a vulnerability** feature. If that feature is unavailable, open an issue asking maintainers for a private contact route without publishing exploit details, credentials or private user data.

The supported deployment is the latest tagged release using `python -m app` or the supplied container. The legacy `server.py` HTTP entry is retained for development/tests.

## Deployment boundaries

- Public mode requires active invitations. Extension tokens and web sessions are separate and revocable.
- A single process owns the bounded in-memory job queue and runtime directory. Horizontal scaling requires a shared durable queue and transactional state first.
- Host and browser-origin checks, bounded request sizes, request deadlines, model network timeouts and bounded workers are enforced. Keep the app behind HTTPS for remote browser sessions.
- Model endpoints are operator configuration. Never accept an arbitrary endpoint or source URL from an analyzed post.
- Keep `.env`, runtime records, private keys and benchmark credentials outside Git and release packages. Run `python tools/check_release.py` before publication.
- Maintain dependencies and model servers. A supported HTTP protocol does not guarantee that every model or server supports vision or strict JSON output.

No security audit or broad accuracy certification is implied by a successful benchmark or test run. Consult the self-hosting guide for the tested controls and current operational limits.
