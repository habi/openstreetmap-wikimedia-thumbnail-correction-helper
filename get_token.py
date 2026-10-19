#!/usr/bin/env python3
"""Get an OSM OAuth 2 access token for the bot account (one-time setup).

1. Logged in as the bot account, register an OAuth 2 application at
   https://www.openstreetmap.org/oauth2/applications/new with
     - Redirect URI: urn:ietf:wg:oauth:2.0:oob
     - Permissions:  "Modify the map" (nothing else is needed; the link below must
                     not ask for more than the application allows, or OSM answers
                     "The requested scope is invalid")
   and note its client ID and client secret.
2. Run this script. It prints a link; open it while logged in as the bot account,
   click "Authorize", and paste the code shown back into the script.
3. The access token is printed on stdout, so it can go straight into the secret:

       python get_token.py | gh secret set OSM_ACCESS_TOKEN

OSM access tokens don't expire; they stay valid until revoked.
"""

import getpass
import sys
from urllib.parse import urlencode

import requests

OSM = "https://www.openstreetmap.org"
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
SCOPES = "write_api"


def ask(prompt: str, secret: bool = False) -> str:
    # Prompts go to stderr / the terminal so stdout only carries the token.
    if secret:
        return getpass.getpass(prompt).strip()
    print(prompt, end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip()


def main() -> int:
    client_id = ask("Client ID: ")
    client_secret = ask("Client secret (hidden): ", secret=True)
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI, "scope": SCOPES}
    print(
        f"\nOpen this link logged in as the BOT account and click Authorize:\n\n"
        f"  {OSM}/oauth2/authorize?{urlencode(params)}\n",
        file=sys.stderr,
    )
    code = ask("Authorization code: ")

    r = requests.post(
        f"{OSM}/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    if not r.ok:
        print(f"Token request failed: {r.status_code} {r.text}", file=sys.stderr)
        return 1
    token = r.json()["access_token"]

    print("Got an access token.", file=sys.stderr)
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
