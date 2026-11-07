"""Base paths of the two member apps (specs/multi-domain §6.7).

One source of truth for Core: navigation, deep links and the role-based entry
read these values. They are product constants, not per-installation
settings: the Vite `base` of the web app and the PWA is fixed at build time,
and one release image serves every installation. The frontends read the same
values from `packages/ui/src/lib/base-paths.ts`; a contract test keeps both
files equal. Renaming a base path later needs a 308 for the old tree and a
retired service worker at the old PWA scope.
"""

from __future__ import annotations

from typing import Final

ADMIN_BASE: Final = "/admin/"
PWA_BASE: Final = "/app/"
