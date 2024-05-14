title: Phones
---
# Phones

The Phone Team (aka POC) provides a comprehensive phone service at EMF.

## Getting Started

You can pick a 4-digit extension number to use, and call anyone on site via it. Create your number in the  [Electromagnetic Phonebook](https://phones.emfcamp.org)

Firstly you will need to register an account with a username, email & password. We send an email validation message from [poc@emfcamp.org](mailto:poc@emfcamp.org) so make sure you’ve clicked that before you can login.

### Registering a Number

Once logged in click Add a Number in the top menu bar.

This will then show you the Create Number form


* **Event** will be EMF2024 (only option)
* **Type of Service **allows you to select what sort of device you want to use this number with, see the section below for more details.
* **Number** should be your desired 4 digit number in the range 2000-8999 or 9200-9899, some numbers may already be taken even if they do not show up in the phonebook.
* **Description** is a free text label for how you want your entry to appear in the phonebook.
* **Public Phonebook** allows you to choose if you want to be in the public listing or not, if not only the Phone Team can see your entry.
* The final field will vary depending on Type of Service, usually you can leave this as it is auto-populated and not editable, you don’t need to make a note of this information you can view it later.

Click Submit and your number will be created.

NOTE:

If you had a Permanent Number Reserved in the Eventphone system and used this on DECT at EMF2022 then we have kept your reservation, please email [poc@emfcamp.org](mailto:poc@emfcamp.org) once you have created an account in our system for us to transfer it over to you.


### Managing your Numbers

The My Numbers link will show you the numbers under your account,

Next to each number is 3 buttons.

**Details** will show you how to use that number with specific instructions for the Type of Service you are using.

**Modify** lets you amend the Description in the phonebook, change the visibility in the phonebook and set a Fallback Number.

The **Fallback Number** is a number that will be called if the main number doesn’t answer the call within 30sec or is unavailable. 


## Types of Service


### DECT 

There's site-wide DECT phone coverage

You can bring your own DECT telephone and join the network, enabling you to call other EMF participants and interactive services for free.

If you're buying a DECT phone and don't know what to get, buy pretty much any Gigaset DECT handset, for example:

- Gigaset A170, £18 on Amazon [https://amzn.to/3yaJ5EG](https://amzn.to/3yaJ5EG)
- Gigaset Life A, ~£60 on Amazon [https://amzn.eu/d/4GuVoMu](https://amzn.eu/d/4GuVoMu) (Known to be compatible with Bluetooth Hearing Aids from Phonak, Unitron and Hansaton)

If you've got one already, feel free to bring it. Use Eventphones [DECT Phone Compatibility List](https://eventphone.de/doku/dect_phone_compatibility_list) to find out if your phone is likely compatible.


### POTS (Plain old telephone service)

There will be a site-wide analog POTS network allowing you to connect a traditional analog phone to a phone line, with support for modems and fax machines.

For more information see docs.cutel.net


### Cellular

We intend to have a GSM (2G) phone network on site. More details to come closer to the event. ( [https://gsm.emf.camp/](https://gsm.emf.camp/) )


### SIP 

You can use SIP devices or a SIP VoIP app on your phone once you've registered an extension number. The credentials will be shown in the Phonebook app.

We would prefer it if people didn’t connect SIP servers to the network eg asterisk as this can expose our network to a large amount of SPAM/fraud, if you want to do this please talk to the phone team.


### Group

A group number will forward incoming calls to up to 10 other numbers, see the section on Group calling for more specific details.


### Apps 

You can register a number as an app and this will point it at our [Jambonz](https://jambonz.org) instance, Jambonz is an open source programmable communications platform, much like Twilio or Infobip.

You will need to host your code somewhere that Jambonz can send a webhook to in order to control what the app does, for more information see the [EMF Developer Docs](https://developer.emfcamp.org)


## Groups

Group numbers have some specific rules and behaviours.

The maximum number of phones that can be under a group is 10

Some Types of Service are not group capable and you won’t be able to add these, for example Apps and Groups (you can’t put a Group in a Group)

There are 2 ways to join/leave a group, via the web interface or by dialling 910, see the Group details page in the Phonebook for more info.

If adding to the group via the web interface you can choose if the member should be rung immediately (0 sec) or after 20 seconds. So creating a 2 stage group. After 20sec all the original 0sec members will still be called too. \
A group cannot have only 20sec members in it.

If a group has no 0sec members then the call will try the Fallback number (if set) or it will play an announcement.


## External Calls

We do not allow attendees to make external calls from the site phone system, if you need to make a call either use your mobile or come to the Info Desk.


### Mobile Coverage

Mobile coverage on site from the public networks is poor, we recommend using WiFi Calling if your handset and network support it.


### WiFi Calling

We have done some work on the WiFi network to enable access for WiFi calling to UK providers, previously this hasn't worked with the IP ranges we use, but we have now solved this. WiFi calling should just work normally, as it does at home, from any of the camp WiFi networks.

If WiFi calling doesn’t work for you on our network (and it normally does at home) please come by the Phone Team tent near admin.


## Test Numbers

90201 - Speaks the caller's assigned number

90202 - More detailed tests, Echo, DTMF, Audio etc. mostly for phone geeks

90210 - For the 90’s kids!
