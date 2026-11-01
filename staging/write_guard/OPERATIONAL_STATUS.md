# Write Guard staging — operational verification 2026-11-01

Not deployed. No ChatGPT -> Guard -> Google Docs write has been demonstrated.

Imported byte-for-byte from ironman_write_guard_staging_20261101_rest_contract_fix.zip, SHA256 3d72ebd9b1b5658bebc405692b4849f2c87bbd9c1ec5644b9c7a04fd23115189 (25 files). Historical 88 local tests were not rerun: this import makes no code change. Existing repository CI does not exercise this standalone directory. No workflow or existing application source is changed.

Live inventory: DigitalOcean droplets ironman-tp-mcp 607975591 and ironman-prefect-staging 609322993 report active. This is inventory, not service health or shell access. The Social deploy receiver is limited to its own service; do not reuse it for Write Guard.

Current session: Google Cloud console returns Site Unavailable on initial navigation and reload. No authenticated GCP console, project inventory, IAM identity, API enablement or billing verification obtained. Local runtime has no google-auth/FastAPI/Uvicorn, ADC selector, identity manifest or WG config. No remote shell administration tool is exposed by the DigitalOcean connector. No remote installation was attempted through unrelated operators.

Code review: make_service_account_connector currently accepts only google.oauth2.service_account.Credentials. Federated/impersonated credentials are explicitly rejected; managed identity support must be reviewed and implemented for the actual selected identity. inbound_api is REST, not an MCP server; a registered authenticated ChatGPT bridge is still missing. Do not claim these are solved by enabling an API or by an existing Drive connection.

Next dependency: an authorized environment with reachable authenticated Google Cloud administration and trusted deployment access to the existing staging host. Then identify the existing project, configure dedicated minimum-scope identity, authorize one sandbox Doc, adapt credential validation to the chosen managed identity, install isolated runtime/persistent ledger/TLS, register ChatGPT connection, and run real successful/duplicate/stale/interruption tests with provider readback. Remove the sandbox Doc afterward. No paid services, existing service changes, credential disclosure or V2 promotion.
