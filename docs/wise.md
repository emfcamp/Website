Bank transfers are processed in response to webhooks from Wise.

We use the statement endpoint, which requires strong customer authentication (SCA). Currently this only involves creating a private key on the server that accesses statements.


Configuring
===========

It's not possible to trigger deposits in Wise's sandbox, so this process is the same for staging and production.

- Create an API token at https://wise.com/settings/ and set `TRANSFERWISE_API_TOKEN` to this in config
- Add a webhook for Balance deposits, pointing to `/wise-webhook`. This won't work unless the app is up and running.
- Create a secure private key and public key:

```
openssl genrsa -out wise-sca.pem 4096
openssl rsa -pubout -in wise-sca.pem -out wise-sca.pub.pem
```

- Point `TRANSFERWISE_PRIVATE_KEY_FILE` to the private key
- Add the public key at https://wise.com/public-keys/ and enable SCA
- Set `TRANSFERWISE_ENVIRONMENT` to `live`
- If you're using a personal account (or have multiple business accounts), set `TRANSFERWISE_PROFILE_ID`

