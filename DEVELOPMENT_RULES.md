# Development Rules

## Git Operations
- **NEVER commit or push to git without explicit user confirmation**
- Always show what changes will be committed
- Always ask "Should I commit and push these changes?" before executing any git commands
- Wait for user's explicit "yes" before running `git add`, `git commit`, or `git push`
- Respect user's decision if they say no or want to modify changes

## Security
- Be extra careful with sensitive files (passwords, API keys, credentials)
- Check .gitignore before committing any new files
- Never commit terraform.tfvars or similar credential files

## General Development
- Always explain what changes are being made
- Ask for confirmation before making significant modifications
- Respect user preferences and boundaries
