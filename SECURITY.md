# Security Considerations

This document outlines security considerations for the Carpet Engine project.

## 🔐 Critical Security Requirements

### 1. Service Account Keys
- **NEVER commit service account keys** to version control
- The `serviceAccountKey.json` file is excluded from git via `.gitignore`
- Always use environment variables to specify the path to your service account key
- Place service account keys in a secure location outside the repository

### 2. Environment Variables
All sensitive configuration should be set via environment variables:

```bash
# Required
SERVICE_ACCOUNT_KEY_PATH=/path/to/your/serviceAccountKey.json
BUCKET_NAME=your-bucket-name

# Optional (for advanced features)
PINECONE_API_KEY=your_pinecone_api_key
OPENAI_API_KEY=your_openai_api_key
```

### 3. Firebase Project Security
- Ensure your Firebase project has proper IAM permissions configured
- Use the principle of least privilege for service accounts
- Regularly rotate service account keys
- Monitor Firebase project usage and access logs

### 4. API Keys (Optional Features)
If using optional features that require external API keys:
- Store API keys securely using environment variables
- Never hardcode API keys in the source code
- Use different API keys for development and production environments
- Regularly rotate API keys

## 🚨 Security Checklist Before Deployment

- [ ] Service account key is not in version control
- [ ] All sensitive configuration uses environment variables
- [ ] Firebase project permissions are properly configured
- [ ] API keys (if used) are stored securely
- [ ] Application is running in a secure environment
- [ ] Logs don't contain sensitive information
- [ ] Error messages don't expose internal details

## 🔍 Security Monitoring

- Monitor Firebase project access logs
- Review application logs for sensitive information
- Regularly audit service account permissions
- Keep dependencies updated for security patches

## 🆘 Reporting Security Issues

If you discover a security vulnerability, please:
1. **DO NOT** create a public issue
2. Email the maintainers directly
3. Provide detailed information about the vulnerability
4. Allow time for the issue to be addressed before public disclosure

## 📚 Additional Resources

- [Firebase Security Rules](https://firebase.google.com/docs/rules)
- [Google Cloud IAM Best Practices](https://cloud.google.com/iam/docs/best-practices)
- [OWASP Security Guidelines](https://owasp.org/www-project-top-ten/) 