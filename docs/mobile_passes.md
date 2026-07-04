# Mobile Passes

## Data Minimisation

In the interests of data-minimisation, we include only the minimum
strictly-required set of information on the pass, since pass contents may be
visible to Apple, Google, or a third-party pkpass-compatible wallet operator.

This means we avoid inclusion of specific attendee PII, like their name or the
_specifics_ of merchandise items they've purchased, and try to warn the user
where necessary (i.e. we can obviously predict that the data transmission
_will_ happen, like Google Wallet) that some pass information will be shared
with their mobile wallet operator.

## Apple Wallet ('pkpass') Passes

The website supports generating Apple Wallet "pkpass" files of a user's checkin code and
purchase info. These are nice because they can be made to show up automatically when the
user's mobile device is near the event, and the UX for showing them on your phone is nicer
than opening a PDF attachment and zooming in on the QR.

### You will need
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

### Setting up
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

### Styling
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

### Locations/beacons
The pass can be automatically shown on iOS devices when the device is near a GPS location or bluetooth le beacon. These are configured in
- `PKPASS_LOCATIONS` (with the distance threshold below which it's shown being `PKPASS_MAX_DISTANCE`)
- `PKPASS_BEACONS`
See the docs for the schema: https://developer.apple.com/documentation/walletpasses/pass
The `relevantText` fields are optional but recommended given the user sees them directly on the lockscreen notification.

### Android
There's no native pkpass support on Android (although Google Wallet _may_ open
and convert one to mixed effect depending on the device), but the format is
portable: third-party readers such as [WalletPasses](https://walletpasses.io/)
or the FOSS [PassAndroid](https://f-droid.org/packages/org.ligi.passandroid/)
parse `pass.json` and render the same fields and artwork. We emit both the
modern `barcodes` array and the deprecated singular `barcode` key so older
readers still show the QR code.

Most Android readers don't verify Apple's signature chain, which is handy for local
testing: a self-signed pass (or one signed with the real cert) opens fine, so you can
preview the generated artwork without an Apple device.

The location/beacon lock-screen surfacing above is Apple-specific. Some Android
readers (e.g. PassWallet) support location notifications, but it's best-effort and not
guaranteed — treat lock-screen relevance as an iOS-only nicety.

## Google Wallet passes

We also support the generation of Google Wallet passes, which are formatted to
the end-user as a URL to pay.google.com, with a signed JWT containing the pass
data. Since this, in all cases, means that information is transmitted to
Google, we make a best effort to try to warn the end user of this and give them
a chance to bail.

Google Wallet splits passes into two halves, the 'class' and the 'object'.
'class'es can have multiple 'object's shared among them, and usually dictate
general information about the event which is being ticketed and information
about the specific ticket type. 'object's contain the specific information for
each pass.

### You will need

- Google Wallet API issuer account
- Google Cloud project
    - Service Account registered in the Wallet API merchant as a 'developer'

### Setting up

You should follow the onboarding guide at
https://developers.google.com/wallet/tickets/events/getting-started/onboarding-guide
- once you've got the Wallet API merchant, and the Service Account (and
associated .json key):

1. Follow the [Wallet onboarding
   guide](https://developers.google.com/wallet/tickets/events/getting-started/onboarding-guide).
1. Place the service account's JSON private key somewhere accessible and set
   `GOOGLE_WALLET_SERVICE_ACCOUNT_KEY` to the path to the file.
1. Put the service account email in `GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL`.
1. Set `GOOGLE_WALLET_ISSUER_ID` to the issuer ID displayed in the [Google Pay
   console](https://pay.google.com/business/console) under "Google Wallet API"
> "Issuer ID".
1. Set `GOOGLE_WALLET_CLASS_ID` to something relevant (e.g. `emf2026test`).
1. Run `./flask tickets googlewallet create-or-update-class` to create the
   class.
1. Enable pass generation with the `ISSUE_GOOGLE_WALLET_TICKETS` feature
   flag.
1. Test it: go to `/account/purchases` and click the Add to Google Wallet
   button. This should prompt you to transmit data to Google and, once
confirmed, take you to the Google Wallet add-pass page.
1. View your pass at https://wallet.google.com/wallet/passes, and make sure it
   looks good on the list page and, once clicked, on the detail page.

### Styling

Unlike PKPass passes, the artwork for Google Wallet passes is always statically
defined; see the constants in `apps/common/walletpass.py`.

### Locations/beacons

Google Wallet passes automatically pick up the locations configured for Apple
Wallet passes. Beacons are not supported.

Note that it isn't possible to configure the max distance (unlike Apple
Wallet).

### Updating

We have support for updating people's Google Wallet passes - we can update them
after issuance using `flask tickets googlewallet update-ticket` with either a
`--email` argument or a `--all-users` parameter. This will update any users
with saved passes in the Google Wallet API, and update things like the current
ticket/parking/campervan/etc. count.
