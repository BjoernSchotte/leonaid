# RustFS

RustFS is the S3-compatible object store of the core stack. API and worker
reach only the internal S3 endpoint; neither the S3 port nor the admin
console is published on the host.

Credentials are created locally by `./leonaid bootstrap`. The POC-010
integration test writes the complete golden dataset as a real object through
Boto3 and verifies bytes, SHA-256 and metadata after all containers restart.
Business document storage follows in POC-092.
