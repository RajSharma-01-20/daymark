# AWS deployment plan (not yet deployed)

This is a learning-project deployment outline. The current code is designed and verified for local development; it is not ready to expose publicly. Do not deploy it with real users or accounts.

## Suggested small-demo architecture

- Build the React UI and serve the static files from a private S3 bucket through CloudFront with Origin Access Control.
- Run the Flask Identity Provider and FastAPI Daymark API as separate container services on ECS Fargate. Put an Application Load Balancer in front with HTTPS certificates from AWS Certificate Manager.
- Use Amazon RDS for PostgreSQL in private subnets. Permit database connections only from the application service security group.
- Store database credentials, Flask session secret, Daymark client secret, and the OIDC signing private key in AWS Secrets Manager. Grant each task execution/application role only the secret access it needs. ECS can inject secrets at task startup; rotating a secret requires restarting/redeploying tasks, as documented by AWS.
- Send application logs to CloudWatch, add health checks, and keep database backups enabled.

## Work needed before deployment

1. Add Dockerfiles and production start commands for both Python services, then build and push images to ECR.
2. Replace localhost issuer, callback, and post-logout URLs with HTTPS hostnames and register those exact URLs in the IdP database.
3. Add a production configuration path for reading the RS256 private key from Secrets Manager or a secure mounted file. The current app expects a local key path.
4. Configure trusted proxy handling, HTTPS-only secure cookies, restrictive CORS, and environment-specific session/client secrets.
5. Add database migrations, production health/readiness checks, and an operational approach for key rotation and backups.
6. Deploy first to a disposable test environment, then verify the complete sign-in, consent, callback, sign-out, and failure paths before sharing the demo.

## AWS references

- [Serve private S3 content through CloudFront with Origin Access Control](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)
- [Amazon ECS: passing Secrets Manager values to containers](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html)
- [Amazon ECS: sensitive data guidance](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/specifying-sensitive-data.html)
- [Amazon RDS: creating and connecting to a PostgreSQL DB instance](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_GettingStarted.CreatingConnecting.PostgreSQL.html)
