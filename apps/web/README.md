# `@leonaid/web`

React entry point for the charity admin back office. For now, the PoC mounts
the build only under `/admin/actions…`; existing identity routes stay in the
lean server until their own migration.

Business mutations run only through the generated `@leonaid/api-client` and the
FastAPI Core.
