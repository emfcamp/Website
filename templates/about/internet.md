title: Internet
---
# Internet

As usual, the EMF Network Operations Centre will be aiming to provide fast wired and wireless networking across the field.

## Wireless
<table class="table">
  <thead>
    <tr><th>Network (SSID)</th><th>Security</th><th></th>
  </thead>
  <tbody>
    <tr><td><code>emf2024</code></td><td>🔐 WPA3 Enterprise 802.1X</td><td>✅ Recommended</td></tr>
    <tr><td><code>emf2024-open</code></td><td>Open (OWE supported)</td><td></td></tr>
  </tbody>
</table>

We recommend you connect to the `emf2024` network for the highest security - this uses WPA Enterprise encryption which will ask for a username and password - you can use **any random username and password** because we only use this for encryption.

The `emf2024-open` network supports [Opportunistic Wireless Encryption](https://en.wikipedia.org/wiki/Opportunistic_Wireless_Encryption) (OWE) which will automatically provide security comparable to a normal WiFi network with a shared password, *if your device supports OWE*. Otherwise, it will be completely unencrypted.

By default, wireless devices are firewalled from the Internet, but inbound connections from other users on the congress network are still allowed.

### Special credentials

There are some special usernames and passwords which can modify the firewall behaviour of the `emf2024` network:

<div class="table-responsive">
<table class="table">
  <thead>
    <tr><th>Username</th><th>Password</th><th>Description</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><code>emf</code></td><td><code>emf</code></td><td>(Or any random username/password.) Filtered connection with public IP address. Inbound connections from the rest of the event are possible, but connections from the Internet are blocked.</td>
    </tr>
    <tr>
      <td><code>outboundonly</code></td><td><code>outboundonly</code></td><td>Filtered connection with public IP address. Inbound connections from the Internet or event are not possible.</td>
    </tr>
    <tr>
      <td><code>allowany</code></td><td><code>allowany</code></td><td>Unfiltered connection with public IP address.</td>
    </tr>
  </tbody>
</table>
</div>

### Bringing wireless access points

Please don’t set up your own access point if at all possible. Wireless airtime is a precious commodity at hacker events, because each additional SSID will transmit 802.11 beacons and management frames, slowing down wireless connectivity for everyone in the area, even if they're not using your network.

If you have no other choice (for running experiments and such), please be nice and follow these rules:

* Do not operate non-WiFi equipment in these frequencies.
* 2.4GHz: use channels 1, 5, 9 or 13 @ 20 MHz. Disable 802.11b.
* 5GHz: use channels 36 or 140 @ 20 MHz.
* Use a minimum data and beacon rate of 12 Mbit/s. Beacon interval 100 ms or higher.
* Only broadcast one SSID. SSID spamming is is very antisocial.
* Do not prefix your broadcasted SSID(s) with “emf”. Do not use other well-known SSIDs.
* Do not use high-gain antennas.
* Limit your transmit power as much as possible, for example to 6 dBm or 4 mW.

## Wired ethernet
All camping areas are within 60m of a datenklo (or data toilet), where you can connect to the network. If you intend to do so please bring 60-70m of CAT5 cable as we are unable to provide any.

**Wired connections are completely unfiltered and will receive a public IP address**. If you have (older) devices that cannot be trusted with unrestricted incoming connections, bring a firewall. 

Lay your own cable neatly from your tent back to the nearest Datenklo, and leave 6m of slack coiled on the floor in front of it. And please lay it so that it can be clearly seen that it needs to be plugged in - or you risk having your cable overlooked. At regular intervals a member of the NOC team will connect it up and enable the port.

Note that most of our ports will not support 10 Mbps - if you need it for old equipment or embedded things, please bring your own switch to convert.

## Contact us

Do you have any questions or special requirements not listed here? Email us at [noc@emfcamp.org](mailto:noc@emfcamp.org) and we can try and help. Yoy can also follow us at [@noc@emfcamp.org](https://social.emfcamp.org/@noc).