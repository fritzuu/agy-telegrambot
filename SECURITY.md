# Security Policy

## Supported Versions

Only the latest release receives active security patches and updates.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Security Best Practices

When operating `agy-telegram-bot`, keep in mind that the bot runs with the permissions of your local user account and can trigger shell commands via `agy`:

1. **Protect your `.env`**: Never commit or publish your `TELEGRAM_BOT_TOKEN`.
2. **Review `AUTO_APPROVE_TOOLS`**: When set to `true`, `agy` will execute tools without interactive confirmation. Only enable this on secure, private networks.
3. **Restrict Bot Access**: Keep your bot username private or configure user whitelist guards.

## Reporting a Vulnerability

If you discover a security vulnerability within this project, please **do not open a public issue**.

Instead, please send an advisory or report directly to the repository maintainer:
- Email: **revanzhafran@gmail.com** (or via GitHub Private Security Advisory)

Please include:
- A description of the vulnerability and its potential impact.
- Step-by-step instructions or proof-of-concept to reproduce the issue.
- Details regarding your environment (OS, Python version, agy version).

We take security issues seriously and will review and respond promptly.
