# Lab Host Setup

This is the runbook for provisioning M5 Max and M5 Pro as student-accessible hosts. Run it once per host. Total time: about 15 minutes per machine, mostly waiting on `ollama pull`.

**Preconditions**

- macOS user with admin rights and `sudo` access (Jay's normal account is fine).
- Tailscale is already installed, signed in, and the host is visible in the Tailscale admin panel.
- Ollama is already installed and running as a LaunchAgent (M5 Max: 0.21.2, M5 Pro: 0.21.0). Confirm with `ollama list`.
- Apple Silicon Homebrew at `/opt/homebrew/bin`. Intel Homebrew (where Ollama lives) at `/usr/local/bin`. Both should exist.

**What you'll end up with**

- A non-admin `student` user on the host with no GUI login presence.
- Tailscale SSH enabled, so authorized tailnet members can SSH in as `student` without managing keys.
- The standard model fleet pre-pulled.
- A working smoke test from another tailnet device.

---

## Step A: Create the shared `student` user

Run on M5 Max and M5 Pro.

```bash
# Generate a random password we'll never use (Tailscale SSH bypasses password auth,
# but macOS requires a password to create the account).
RAND_PW=$(openssl rand -base64 24)

sudo sysadminctl -addUser student \
  -fullName "Lab Student" \
  -password "$RAND_PW" \
  -home /Users/student \
  -shell /bin/zsh

# Confirm the account exists and check group membership.
dscl . -read /Users/student | grep -E '^(RecordName|UniqueID|PrimaryGroupID|NFSHomeDirectory|UserShell):'
dseditgroup -o checkmember -m student admin   # should print "no"
dseditgroup -o checkmember -m student wheel   # should print "no"
```

If `student` ended up in `admin`, remove them:

```bash
sudo dseditgroup -o edit -d student -t user admin
```

`staff` membership is the macOS default for any new user and is fine; you don't need to remove it.

Forget the password we generated. We will never type it.

---

## Step B: Restrict the user

### Hide from the login window

```bash
sudo dscl . create /Users/student IsHidden 1
```

This keeps `student` from appearing on the GUI login screen and the Fast User Switching menu. The account still exists for SSH sessions.

### Confirm the shell and PATH

`sysadminctl` already set the shell to `/bin/zsh`. Now make sure `student`'s PATH picks up Ollama. Ollama installs to `/usr/local/bin` (Intel Homebrew prefix) on these hosts, and Apple Silicon Homebrew lives at `/opt/homebrew/bin`. Apple Silicon first, then Intel:

```bash
sudo -u student tee /Users/student/.zshrc > /dev/null <<'EOF'
# Apple Silicon Homebrew first (gh, git, python3, rsync), then Intel (ollama).
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Quiet, useful prompt.
PROMPT='%n@%m %1~ %# '
EOF

sudo chown student:staff /Users/student/.zshrc
sudo chmod 644 /Users/student/.zshrc
```

Sanity check: open an SSH session as `student` (after Step C is done) and run `which ollama`. It should print `/usr/local/bin/ollama`.

---

## Step C: Enable Tailscale SSH

On each host:

```bash
sudo tailscale up --ssh
```

Re-authorizing won't change other Tailscale settings; `--ssh` is additive. If the host was already running `tailscale up`, this just flips the SSH bit on.

Confirm:

```bash
tailscale status | grep "$(hostname -s)"
```

You should see the host listed with its tailnet IP. SSH-enabled hosts also show up in the Tailscale admin panel under Machines with an "SSH" badge.

(The ACL in `tailscale-acl.md` controls *who* can SSH and *as which user*. This step just makes the host willing to accept Tailscale SSH at all.)

---

## Step D: Pre-pull the standard model fleet

The Ollama daemon stores models in a single shared cache per host (under the daemon-running user's home). `ollama pull` is idempotent — already-present models are skipped — so running this as `student` is safe and confirms `student`'s view sees the daemon. Run the right list per host.

**M5 Max** (heavy fleet — qwen3.6 / qwen2.5 / llama3.3 / gemma4 / both embedders):

```bash
sudo -u student -i bash -c '
  ollama pull qwen3.6:27b-coding-mxfp8
  ollama pull qwen3.6:35b-a3b-coding-nvfp4
  ollama pull qwen2.5:72b-instruct-q4_K_M
  ollama pull llama3.3:70b-instruct-q4_K_M
  ollama pull gemma4:31b
  ollama pull gemma4:26b
  ollama pull nomic-embed-text
  ollama pull bge-m3
'
```

**M5 Pro** (qwen3.5 family + gemma4 + English embedder):

```bash
sudo -u student -i bash -c '
  ollama pull qwen3.5:35b-a3b-nvfp4
  ollama pull qwen3.5:35b-a3b-coding-nvfp4
  ollama pull qwen3.5:27b-q8_0
  ollama pull gemma4:31b
  ollama pull gemma4:26b
  ollama pull gemma4:e4b
  ollama pull nomic-embed-text
'
```

Notes:

- The lists are **subsets of what the daemon already serves** — Jay's existing pulls are visible to `student` because the daemon is shared. If a host already has every line, every pull is a no-op and Step D becomes a verification rather than a download.
- `qwen3.6:35b`, `qwen3.6:latest`, `qwen3.6:35b-a3b-nvfp4` are reserved for Jay's research workload (psychrx POC on M5 Pro). Don't add them to the student-facing list. Students ignoring the reservation costs nothing technically — it's a social rule, documented in `student-onboarding.md`.
- M5 Max (128 GB unified) can hold most of this fleet warm at once; M5 Pro (48 GB) will rotate dense models in and out under load.
- A fresh full pull is roughly 100 GB on M5 Max, 60 GB on M5 Pro. Run on Wi-Fi with a power adapter. On already-provisioned hosts this step is fast.

Confirm from inside `student`'s shell:

```bash
sudo -u student -i ollama list
```

The daemon's full list will print — including reserved tags. That's expected; the reservation is documented, not enforced at the daemon.

---

## Step E: Smoke test from another tailnet device

From M3 Pro (or any other authorized tailnet machine):

```bash
# 1. Land in the student shell.
ssh student@m5-max
# expected: prompt changes to "student@m5-max ~ %", no password asked,
#           Tailscale SSH handles auth.

# 2. From inside that session:
which ollama         # /usr/local/bin/ollama
ollama list          # all seven canonical models
ollama run gemma4:e4b "hello"   # short response in a few seconds

exit
```

Repeat for `m5-pro`. Both should succeed.

If `ssh student@m5-max` asks for a password, Tailscale SSH didn't take. Re-check Step C and the ACL (`tailscale-acl.md`).

---

## Rollback

To remove the lab provisioning from a host:

```bash
# Disable Tailscale SSH (the host stays on the tailnet, just won't accept SSH).
sudo tailscale up --ssh=false

# Or take the host fully off the tailnet.
sudo tailscale down

# Delete the student user and home dir.
sudo sysadminctl -deleteUser student
sudo rm -rf /Users/student   # only if sysadminctl didn't already
```

These are reversible: re-running Step A through Step C restores the host.

---

## Maintenance touchpoints

- **Ollama upgrade.** When Felix bumps Ollama on a host, re-test `sudo -u student -i ollama list` to confirm `student`'s view of the model store didn't change.
- **Fleet additions.** New canonical models go in Step D's pull list and need to be pulled under `student` on each host.
- **Student offboarding.** Removing a student from the tailnet (or untagging them) cuts SSH access immediately. The shared `student` account stays; nothing per-student to clean up.
