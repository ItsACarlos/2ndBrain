# Rclone Setup: Initial Configuration

This guide covers the first-time setup of rclone for 2ndBrain. You only
need to do this once on your **server machine**. After that, workstations
can simply copy the encrypted configuration file via `scp`.

The goal is to:
1. Create a restricted OAuth token for a specific Google Drive folder
2. Create an encrypted `rclone.conf` file that 2ndBrain will use

```{note}
**GPG is not needed here.** The `rclone.conf` file itself is encrypted
using rclone's native encryption feature. GPG is set up separately later
(in step 5 of the Quick Start) to encrypt the **password** that protects
the rclone.conf file — that's a different layer of security for runtime
access to the config.
```

## Prerequisites

**Minimum rclone version: 1.58.0** (required for `bisync` command)

### Ubuntu/Debian/Mint

```bash
sudo apt install rclone
rclone version  # Verify it's ≥ 1.58.0
```

### RHEL/CentOS 8: Upgrade rclone

The RHEL8 repository includes rclone 1.57.0, which lacks the `bisync`
command. Install the latest version directly from rclone.org:

```bash
# Download and install latest rclone
curl https://rclone.org/install.sh | sudo bash

# Verify version (should be ≥ 1.58.0)
rclone version
```

(rhel-centos-8-upgrade-rclone)=
### RHEL/CentOS 8: Upgrade rclone

### Fedora/CentOS Stream

Newer Fedora releases have rclone ≥ 1.58.0:

```bash
sudo dnf install rclone

# Verify version
rclone version
```

## Step 1: Create a Restricted Google Drive OAuth Token

You need to create a Google Cloud project with restricted access to a
**single Google Drive folder**. This is safer than using your entire Drive.

### 1.1 Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a Project** → **New Project**
3. Name it (e.g., "2ndBrain Vault")
4. Click **Create**

### 1.2 Enable the Google Drive API

1. In the Cloud Console, go to **APIs & Services** → **Enabled APIs & Services**
2. Click **+ Enable APIs and Services**
3. Search for "Google Drive API"
4. Click it, then click **Enable**

### 1.3 Create an OAuth 2.0 Credential

1. Go to **APIs & Services** → **Credentials**
2. Click **+ Create Credentials** → **OAuth Client ID**
3. If prompted, click "Configure Consent Screen" first:
   - Choose **External** user type
   - Fill in the app name (e.g., "2ndBrain")
   - Add your email as a test user
   - Save and continue
4. Back on the Credentials page, click **+ Create Credentials** → **OAuth Client ID**
5. Choose **Desktop application**
6. Name it (e.g., "2ndBrain Rclone")
7. Click **Create** — you'll see a client ID and secret

### 1.4 Create a Shared Google Drive Folder

1. Go to [Google Drive](https://drive.google.com/)
2. Create a new folder named `2ndBrain-vault` (or your preferred name)
3. Note its **folder ID** from the URL: `https://drive.google.com/drive/folders/FOLDER_ID`
4. You'll pass this to rclone below

## Step 2: Create the Encrypted rclone.conf File

Run `rclone config` to create and encrypt the configuration:

```bash
rclone config
```

Follow the prompts:

```
n) New remote
name> gdrive-vault
Storage> drive
client_id> <paste your OAuth client ID>
client_secret> <paste your OAuth client secret>
scope> 1  (Full access, we'll restrict via folder ID below)
root_folder_id> <paste your folder ID from Step 1.4>
service_account_file> <leave blank>
use_trash> y
config_token> <leave blank, will authorize below>
```

When asked if you'd like to authorize with Adv config, say `n`.

A browser window will open — **sign in with your Google account** and
grant permission. The token will be saved to `rclone.conf`.

### 2.1 Encrypt the rclone.conf File

After the config is created, rclone will ask if you want to encrypt it:

```
encrypt the password> y
```

You'll be prompted to enter a **password** to encrypt the config file:

```
Enter password for encryption:
Confirm password:
```

**Save this password** — you'll need it later when setting up the
credential encryption system (GPG or systemd-creds in step 5 of the
Quick Start).

The encrypted config is now at `~/.config/rclone/rclone.conf`.

## Step 3: Verify the Configuration

```bash
rclone lsd gdrive-vault:
```

You should see the contents of your `2ndBrain-vault` folder. If you see
your entire Google Drive or an error, check that `root_folder_id` is
set correctly in the config.

## For Workstations

Once the server has a working `rclone.conf`, workstations only need to
copy it:

```bash
# On the workstation, copy the encrypted config from the server
scp user@server:~/.config/rclone/rclone.conf ~/.config/rclone/

# Ensure correct permissions
chmod 600 ~/.config/rclone/rclone.conf
```

That's it — no need to repeat the OAuth setup on each machine. The same
encrypted config works everywhere.

## Next Steps

Return to the [Quick Start](../tutorials/quickstart.md#deploy) to
install 2ndBrain using `./scripts/install.sh`, then proceed to
step 5 (credential encryption) where you'll set up GPG or systemd-creds.

## Troubleshooting

### "Transport endpoint not connected" (stale mount)

If rclone crashes and leaves a dead FUSE mount:

```bash
fusermount -uz ~/Documents/2ndBrain
systemctl --user restart rclone-2ndbrain.service
```

### Check rclone logs

```bash
journalctl --user -u rclone-2ndbrain.service -f
```

### Verify the folder is mounted

```bash
ls ~/Documents/2ndBrain/
```

If empty or shows an error, check the service status and logs above.
