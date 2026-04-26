# Tailscale ACL for the Student Lab

This is the ACL Jay pastes into `login.tailscale.com/admin/acls`. Tailscale's ACL editor replaces the entire policy file every time you save, so this snippet is the full policy, not a partial.

## Goals

- Students can SSH to **`tag:lab` hosts only** (M5 Max, M5 Pro), as the OS user `student`.
- Students cannot SSH to M3 Pro (it has no `tag:lab`).
- Students cannot reach any other tailnet device on any other port.
- Jay (`autogroup:owner`) keeps full access to everything.
- No SSH keys to distribute. Tailscale SSH is the auth layer.

## Approach in four lines

1. Tag the lab hosts with `tag:lab` from the admin UI (per-host, one-time).
2. Tag each student account with `tag:student` from the admin UI (per-user, on invite).
3. ACL `acls` block: deny-by-default, allow `tag:student` to reach `tag:lab` on port 22 only.
4. ACL `ssh` block: allow `tag:student` to Tailscale-SSH into `tag:lab` as the OS user `student`, with `check` mode so Tailscale prompts for re-auth on a sensible cadence.

---

## The ACL JSON

Paste this whole block into the ACL editor. It's a strict superset of "default policy" minus the wildcard allow, plus the lab-specific rules.

```jsonc
{
  // Tag owners: who is allowed to apply / approve a given tag.
  // Only Jay can mint tag:lab and tag:student.
  "tagOwners": {
    "tag:lab":     ["autogroup:owner"],
    "tag:student": ["autogroup:owner"]
  },

  // ACL rules. Tailscale evaluates top-to-bottom; first match wins.
  // No implicit allow-all. Anything not matched is denied.
  "acls": [
    // Jay (account owner) can reach anything on the tailnet.
    {
      "action": "accept",
      "src":    ["autogroup:owner"],
      "dst":    ["*:*"]
    },

    // Students can reach lab hosts, on SSH only.
    // Port 22 is the only port we open; this blocks Ollama's 11434 from being
    // hit directly across the tailnet. Students get to Ollama by SSHing in
    // and running `ollama` locally on the host, or by `ssh -L` port-forwarding.
    {
      "action": "accept",
      "src":    ["tag:student"],
      "dst":    ["tag:lab:22"]
    }

    // No other rules. Anything else (student-to-student, student-to-M3-Pro,
    // student-to-anything-not-tag:lab) falls through and is denied.
  ],

  // Tailscale SSH policy. This is what makes `ssh student@m5-max` work
  // without classic SSH keys.
  "ssh": [
    // Students SSH into lab hosts as the OS user `student`.
    // `check` mode means Tailscale prompts for a fresh auth check periodically
    // (default ~12h), comfortable for daily use, tight enough that a stolen
    // device session expires.
    {
      "action": "check",
      "src":    ["tag:student"],
      "dst":    ["tag:lab"],
      "users":  ["student"]
    },

    // Jay can SSH into anything as any local user, no recheck.
    {
      "action": "accept",
      "src":    ["autogroup:owner"],
      "dst":    ["*"],
      "users":  ["autogroup:nonroot", "root"]
    }
  ],

}
```

The core (`acls` + `ssh`) is what enforces the access model. Tighter session lifetimes for `tag:student` (so a forgotten laptop isn't a permanent backdoor) can be configured later via Device Approval or per-tag session duration in the admin UI; not required for the v1 cutover.

---

## Host tagging steps (M5 Max, M5 Pro)

Tags on hosts are set in the Tailscale admin UI, **not** by the client.

1. Go to `login.tailscale.com/admin/machines`.
2. Find **M5 Max** in the list (Tailscale will show whatever its hostname is, e.g. `georges-macbook-pro`).
3. Click the three-dot menu on its row, choose **Edit ACL tags**.
4. Add `tag:lab`. Save.
5. Repeat for **M5 Pro** (`sophies-mbp` or whatever its hostname is).
6. **Do not** tag M3 Pro. Its absence from `tag:lab` is what blocks student access.

After tagging, the Machines page should show the `tag:lab` badge next to the two lab hosts only.

(You'll also need to re-authenticate the host once after tagging if Tailscale prompts you. `sudo tailscale up --ssh` re-runs the login flow.)

---

## User tagging steps (each student)

Tailscale tags are normally for non-human nodes, but `tag:student` works fine for users when applied via the per-user ACL tag assignment.

The cleanest pattern:

1. Invite the student to the tailnet via `login.tailscale.com/admin/users` → **Invite users** → enter their email.
2. They accept the email invite and install Tailscale on their device.
3. Once their device shows up in `Machines`, click into the device, choose **Edit ACL tags**, and add `tag:student`.
4. Confirm the device row now shows the `tag:student` badge.

If you want to skip per-device tagging on every new student, you can use **autoApprovers** to auto-tag any device signed in by a specific user email. # verify against Tailscale docs: current key is `autoApprovers.routes` and `autoApprovers.exitNode`; user-tag autoApproval may live under `nodeAttrs` or `grants`. The manual per-device path always works; auto-approval is a nice-to-have once the cohort is stable.

---

## Test plan

Run from M3 Pro (which has no `tag:lab` and no `tag:student`, so it should behave like Jay's normal device).

```bash
# 1. Tailscale sees both hosts.
tailscale status | grep -E '(m5-max|m5-pro|georges|sophies)'

# 2. As Jay (no tag:student), SSH to a lab host using Tailscale SSH.
tailscale ssh student@m5-max
# expected: lands in student's shell. Jay reaches everything.
exit

# 3. (From a test device with tag:student applied) SSH to a lab host.
ssh student@m5-max
# expected: Tailscale SSH prompt → re-auth → lands in student's shell.

# 4. (From the same tag:student device) Try to SSH to M3 Pro.
ssh jaypark@<m3-pro-tailnet-name>
# expected: connection refused or denied by ACL. M3 Pro has no tag:lab,
#           and the only acls rule for tag:student is tag:lab:22.

# 5. (From the same tag:student device) Try to hit Ollama directly.
curl http://m5-max:11434/api/tags
# expected: connection refused. Port 11434 is not in the ACL for tag:student;
#           students must SSH in or use `ssh -L` port-forwarding.

# 6. (From the same tag:student device) SSH to m5-pro.
ssh student@m5-pro
# expected: works. m5-pro is also tag:lab.
```

If step 3 lands a student in **Jay's** shell instead of `student`'s, the `ssh` ACL block didn't restrict the `users` field correctly. Re-check that `"users": ["student"]` is set on the `tag:student` → `tag:lab` rule.

If step 4 succeeds when it should fail, the deny-by-default isn't holding. Check that the `acls` block doesn't contain a stray wildcard rule.

---

## Rollback

To take students off the tailnet entirely, remove `tag:student` from each student device (Machines → Edit ACL tags → remove tag). The ACL still enforces deny-by-default for them.

To temporarily lock everyone out of the lab without touching the ACL, run `sudo tailscale up --ssh=false` on M5 Max and M5 Pro (per the host setup runbook).

To revert the ACL itself, the admin UI keeps a version history. Pick the previous policy and restore.
