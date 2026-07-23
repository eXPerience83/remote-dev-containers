## What changed

<!-- Summarize the change and the reason for it. -->

## Impact

<!-- Describe user, deployment, image-size, persistence, compatibility or security impact. -->

## Validation

<!-- List the commands, CI jobs and manual checks used. -->

- [ ] `make validate`
- [ ] Relevant build or smoke test completed
- [ ] Documentation updated when behavior changed
- [ ] `CHANGELOG.md` updated when user-visible behavior changed

## Safety and release checks

- [ ] No credentials, tokens, private hostnames or personal infrastructure paths were added
- [ ] No privileged mode, host networking or Docker socket mount was introduced
- [ ] Public ttyd exposure remains authenticated and is not presented as Internet-safe
- [ ] Image tags, digests and rollback guidance remain accurate
- [ ] This change does not publish or promote a stable release unintentionally

## Follow-up

<!-- Note deferred work, known limitations or rollback instructions. -->
