# Remote controller access

The recommended demo architecture is:

Browser -> HTTPS public hostname -> Cloudflare Tunnel -> Raspberry Pi localhost:8080 -> printer/camera

The Raspberry Pi initiates the tunnel connection outbound. Do not forward TCP/8080 on the router.

## One-time Cloudflare setup

1. Put a domain in Cloudflare.
2. In Cloudflare, create a remotely-managed Tunnel for this Raspberry Pi.
3. Add a Published Application route, for example:
   - Public hostname: `bioprinter.example.com`
   - Service: `http://localhost:8080`
4. Add a Cloudflare Access policy to the hostname so only approved users can reach it.
5. Install `cloudflared` on the Pi using Cloudflare's current Linux instructions.
6. From this repo run:

   ```bash
   cd ~/VT_Bioprinter_Control
   sudo bash raspberry_pi/install_remote_access.sh https://bioprinter.example.com
   ```

   The script prompts for the Tunnel token without echoing it.

After setup, `cloudflared.service` starts at boot and reconnects whenever the Pi has Internet access.

## Security model

- Keep the existing VT Bioprinter controller access token enabled.
- Put Cloudflare Access in front of the public hostname as a second authentication layer.
- Do not expose port 8080 directly to the Internet.
- Physical emergency stop / printer power cutoff remains local and primary.
- Remote motion still uses the controller's commissioning and preflight gates.

## Multiple Wi-Fi networks

The Network page stores multiple NetworkManager Wi-Fi profiles. Each profile has an autoconnect priority. Higher values are preferred. If the preferred network is unavailable, NetworkManager can choose the next available saved profile.

The setup hotspot remains the recovery path when normal Wi-Fi is unavailable.
