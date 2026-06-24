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
1. Test it: go to `/account/purchases` and click the Add to Apple Wallet button. This should download and show the pass on a Mac or iOS device. If it doesn't, something's wrong - most likely with the signing. You can debug by looking at console.app messages on a Mac (search for "pass").

## Styling
The pass is an "event ticket" pass. Its artwork is generated at runtime from the
site's existing brand assets (see `get_pass_assets` in `apps/common/pkpass.py`), so
there are no pass-specific images to maintain:
- `icon.png` (lockscreen/notifications) - the EMF glyph on a brand-orange tile
- `logo.png` (shown on the pass) - the white EMF wordmark
- `background.png` (shown blurred behind the pass) - the hero graphic

`@2x` and `@3x` variants of each are produced automatically.

To use bespoke artwork instead, point `PKPASS_ASSETS_DIR` at a directory containing
the files above (plus their `@2x`/`@3x` variants, and optionally `strip.png`). See
the (somewhat out of date) Apple docs at
https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/PassKit_PG/Creating.html.

## Locations/beacons
The pass can be automatically shown on iOS devices when the device is near a GPS location or bluetooth le beacon. These are configured in
- `PKPASS_LOCATIONS` (with the distance threshold below which it's shown being `PKPASS_MAX_DISTANCE`)
- `PKPASS_BEACONS`
See the docs for the schema: https://developer.apple.com/documentation/walletpasses/pass
The `relevantText` fields are optional but recommended given the user sees them directly on the lockscreen notification.

## Android
There's no native pkpass support on Android (Google Wallet won't open one), but the
format is portable: third-party readers such as
[WalletPasses](https://walletpasses.io/) or the FOSS
[PassAndroid](https://f-droid.org/packages/org.ligi.passandroid/) parse `pass.json`
and render the same fields and artwork. We emit both the modern `barcodes` array and
the deprecated singular `barcode` key so older readers still show the QR code.

Most Android readers don't verify Apple's signature chain, which is handy for local
testing: a self-signed pass (or one signed with the real cert) opens fine, so you can
preview the generated artwork without an Apple device.

The location/beacon lock-screen surfacing above is Apple-specific. Some Android
readers (e.g. PassWallet) support location notifications, but it's best-effort and not
guaranteed — treat lock-screen relevance as an iOS-only nicety.