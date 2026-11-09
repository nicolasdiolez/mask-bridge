# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately:

- on GitHub, with **Security › Report a vulnerability** in this repository;
- or by email to maskbridge@nicolasdiolez.com.

Include the Mask Bridge version, your system and Lightroom Classic version, and the steps to reproduce. If you add a diagnostic report, read it first: it contains local paths and photo file names.

## Scope

Mask Bridge runs on your computer. The engine listens only on 127.0.0.1, refuses requests from web pages, requires the token of its session for everything except its status check (`/health`), and makes no network connection during use. In scope: the engine's local server, the handling of files and paths (originals must never be overwritten), the changes made to the Lightroom catalog, and the build, signing and release scripts.

## Supported versions

Fixes go into the latest release only, currently 1.2.x.
