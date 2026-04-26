# Lab Host Setup

Minimal v2 setup. The lab uses a shared `student` user account on each host, with a single shared password Jay distributes privately. No Tailscale ACL, no Tailscale SSH, no public-key management — classic SSH over the tailnet, password auth.

## Preconditions

- macOS user with admin rights and `sudo` access (Jay's normal account is fine).
- Tailscale already installed, signed in, host visible in the Tailscale admin panel.
- Ollama installed and running as a LaunchAgent (M5 Max: 0.21.2, M5 Pro: 0.21.0). `ollama list` should print the canonical fleet.
- Remote Login already on (System Settings → General → Sharing → Remote Login). Verify by SSHing as your normal user from another machine.

## One-time per host

Run on M5 Max and M5 Pro. Pick a single shared password Jay can distribute to students; substitute it for `<SHARED_PASSWORD>` below.

```bash
sudo -v

sudo sysadminctl -addUser student \
  -fullName "Lab Student" \
  -password "<SHARED_PASSWORD>" \
  -home /Users/student \
  -shell /bin/zsh

sudo createhomedir -c -u student

sudo dseditgroup -o edit -d student -t user admin 2>/dev/null || true
sudo dseditgroup -o edit -d student -t user wheel 2>/dev/null || true

sudo dscl . create /Users/student IsHidden 1

sudo -u student tee /Users/student/.zshrc > /dev/null <<'ZSHRC'
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
PROMPT='%n@%m %1~ %# '
ZSHRC
sudo chown student:staff /Users/student/.zshrc
sudo chmod 644 /Users/student/.zshrc
```

Notes:
- `sysadminctl` only *assigns* a home directory; it does not create one. `createhomedir -c -u student` populates `/Users/student/` from `/System/Library/User Template/` (Desktop, Documents, Library, etc.) with correct ownership. Skip it and `sudo -u student -i` will print "unable to change directory to /Users/student" forever.
- Don't put inline `#` comments on commands you paste into zsh on macOS; default zsh doesn't honor `#` as a comment in interactive mode and it gets parsed as an argument. Comments live above the command, not on the same line.

Verify:

```bash
id student                            # uid/gid printed; staff group only
dscl . -read /Users/student NFSHomeDirectory UserShell IsHidden
sudo -u student -i which ollama       # /usr/local/bin/ollama
```

## Smoke test from another tailnet device

From M3 Pro (or any other authorized tailnet machine):

```bash
ssh student@georges-macbook-pro
# expected: prompt for password, paste <SHARED_PASSWORD>, lands in
#           student@Georges-MBP ~ %
which ollama         # /usr/local/bin/ollama
ollama list          # full fleet, identical to what Jay sees
ollama run gemma4:e4b "hello"   # short response in a few seconds
exit
```

Repeat for `sophies-macbook-pro`. Both should succeed.

## Maintenance

- **Add a student.** Invite their email at `login.tailscale.com/admin/users`. Once they accept, send `ssh student@<host>` and the shared password over a private channel.
- **Remove a student.** Revoke them from the tailnet (admin UI → Users → remove). If you want to be thorough, rotate the shared password (`sudo dscl . -passwd /Users/student "<new password>"`) and re-share with the remaining cohort.
- **Audit who connected.** `login.tailscale.com/admin/logs` shows tailnet connection events per device.

## Rollback

To remove the lab provisioning from a host:

```bash
# Delete the student user and home dir.
sudo sysadminctl -deleteUser student
sudo rm -rf /Users/student   # only if sysadminctl didn't already
```

Reversible: re-running the provisioning block restores the host.
