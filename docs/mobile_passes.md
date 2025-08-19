The website supports generating Apple Wallet "pkpass" files of a user's checkin code and
purchase info. These are nice because they can be made to show up automatically when the
user's mobile device is near the event, and the UX for showing them on your phone is nicer
than opening a PDF attachment and zooming in on the QR.

## You will need
- An Apple Developer Program suscription/team
- To set the following config options (see development-example.cfg)
    - `PKPASS_TEAM_ID`
    - `PKPASS_IDENTIFIER`
    - `PKPASS_SIGNER_CERT_FILE`
    - `PKPASS_KEY_FILE`
    - `PKPASS_CHAIN_FILE`
    - `PKPASS_ASSETS_DIR`
    - `PKPASS_LOCATIONS` (optional)
    - `PKPASS_MAX_DISTANCE` (optional)
    - `PKPASS_BEACONS` (optional)

## Setting up
To generate pkpasses that will be accepted by Apple devices, you will need an apple
developer account with active developer program subscription.

1. Go to Apple developer console > Certificates, Identifiers & Profiles > Identifiers.
1. Set `PKPASS_TEAM_ID` config option to be the development team id
1. Click "+" and create a "Pass Type ID". Give it a sensible identifier, and then use this
  as `PKPASS_IDENTIFIER`.
1. Generate a private key: `openssl genrsa -out pkpass.key 2048`. Point `PKPASS_KEY_FILE` to this file.
1. Generate a CSR from the private key: `openssl req -new -key pkpass.key -out pkpass.csr`
    - Fill out the details - doesn't seem to matter much what you use
    - Leave the challenge password blank.
1. Get Apple to generate a certifcate from the CSR: click the pass type identifier, then
   create certificate, and upload the CSR.
1. You'll get a shiny `pass.cer`. Convert it to base64 (pem/crt) text format:
   `openssl x509 -inform der -in pass.cer -out pkpass.crt`. Point `PKPASS_SIGNER_CERT_FILE` to this file
1. Download Apple's root and convert it to text format:
   `curl -L http://developer.apple.com/certificationauthority/AppleWWDRCA.cer | openssl x509 -inform der -out applewwdrca.crt`. Point `PKPASS_CHAIN_FILE` to this file.
1. Enable pkpass generation with the `ISSUE_APPLE_PKPASS_TICKETS` feature flag.
1. Test it: go to `/account/purchases` and click the add to wallet button. This should download and show the pass on a Mac or iOS device. If it doesn't, something's wrong - most likely with the signing. You can debug by looking at console.app messages on a Mac (search for "pass").

## Styling
The pass can be styled with the assets in `images/pkpass`. Optionally can be overridden with `PKPASS_ASSETS_DIR`. See (somewhat out of date) docs at https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/PassKit_PG/Creating.html.
Note that our pass is an "event ticket" pass - so you should use:
- `icon.png` - shown on the lockscreen/in notifications
- `logo.png` - shown on the pass itself
- `background.png` - shown (blurred) in the background of the pass
- `strip.png` - optionally shown below the pass name as background to the ticket number information

There should be @2x and @3x variants of all the above too.

## Locations/beacons
The pass can be automatically shown on iOS devices when the device is near a GPS location or bluetooth le beacon. These are configured in
- `PKPASS_LOCATIONS` (with the distance threshold below which it's shown being `PKPASS_MAX_DISTANCE`)
- `PKPASS_BEACONS`
See the docs for the schema: https://developer.apple.com/documentation/walletpasses/pass
The `relevantText` fields are optional but recommended given the user sees them directly on the lockscreen notification.