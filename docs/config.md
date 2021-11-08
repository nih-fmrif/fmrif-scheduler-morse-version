---
title: Configuration
...
\pagebreak
The site gets static configuration from two sources: environment variables and `config.json`. The environment variables control how the site interacts with external resources like the database and `config.json` sets configuration for the site that is true irrespective of the outside world. Each will be covered in turn. Changing any of this configuration requires the site to be restarted and it will fail to restart if there is an error in the configuration.

# Environment variables

Only some of these environment variables must be set. Most can be left to their default. If they are required, it will be explicitly noted.

The manner in which they are set is unimportant as long as they can be read by the python process.

## `MMSCHED_SERVER_NAME`

This sets the domain of the server. It is only used when interacting with the site from the command line but must be set.

## `MMSCHED_APPLICATION_ROOT`

This sets an optional url prefix for the site. For example if the site is hosted at `https://domain.example.com/scheduler` instead of just `https://domain.example.com/` then this must be set to `scheduler`.

## `MMSCHED_DB_URL`

The url for connecting to the postgres database. This must be specified.

## `MMSCHED_MAIL_SERVER` and `MMSCHED_MAIL_PORT`

The address and port of the smtp server used for sending email. If either is absent they default to localhost and 25, respectively.

## `MMSCHED_MAIL_USE_TLS` and `MMSCHED_MAIL_USE_SSL`

These are booleans and anything other than the empty string or the string `false` is considered true, but using the string `true` is recommended to avoid confusion. These would only need to be true if your mail server explicitly requires them to be set as many mail servers automatically negotiate these settings.

## `MMSCHED_MAIL_USERNAME` and `MMSCHED_MAIL_PASSWORD`

These are the username and password for logging into the smtp account that sends email. These must be specified.

## The `MM_SCHED_X_FORWARDED_*` proxy count environment variables

The below environment variables are optional (absence defaults to 0):

* `MMSCHED_X_FORWARDED_FOR`
* `MMSCHED_X_FORWARDED_PROTO`
* `MMSCHED_X_FORWARDED_HOST`
* `MMSCHED_X_FORWARDED_PORT`
* `MMSCHED_X_FORWARDED_PREFIX`

They correspond to the following http headers:

* `X-Forwarded-For`
* `X-Forwarded-Proto`
* `X-Forwarded-Host`
* `X-Forwarded-Port`
* `X-Forwarded-Prefix`

Each variable must correctly count the 0 or more proxy servers that will be adding that respective header. It's necessary to have a correct count of each so that the user's ip address may be determined securely. [See the flask documentation for more information about the proxy headers](https://werkzeug.palletsprojects.com/en/2.0.x/middleware/proxy_fix/).

\pagebreak
# `config.json`

The `config.json` file must be in the scheduler directory. It consists of a single object where all of the below keys are mandatory.

## `secret_key`

The secret key used for signing session cookies. [See the flask documentation for more info about the secret key](https://flask.palletsprojects.com/en/2.0.x/config/#SECRET_KEY).

## `site_default_sender`

This is the email address that will be used by the site to send emails.

## `listserv`

The email address for the listserv that holds the mailing lists of the mail action form.

## `mailing_lists`

This is an object with 0 or more entries that configures the mail action form. Each entry key is the name of a mailing list to include on the mail action form and each value is a string describing that mailing list (the descriptions may be the empty string). If no entries are included, the mail action form cannot be used.

## `nih_networks`

This is a list of strings, containing one or more entries. Each string is an ip address or subnet. This is used to determine access for pages that can only be accessed over the NIH network.