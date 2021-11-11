---
title: Command line interface
...
\pagebreak
# Commands
All commands listed are subcommands of the `flask` script and hence need to be run through `pipenv` as
```sh
pipenv run flask SUBCOMMAND [ARGUMENTS]
```
or, when in a `pipenv shell`, just
```sh
flask SUBCOMMAND [ARGUMENTS]
```

Failure to execute them inside `pipenv` will result in no harm other than a large number of errors about not being able to find necessary resources.

The configuration described in `config.pdf` must be in place to execute any of these subcommands.

## `force-login`

The `force-login` subcommand requires a valid username (`tlkpresearcher.researchercode`). If the username is invalid it reports an error, otherwise it returns a url for the site. Pasting this url into a browser will log you into the site as that user if SiteMinder is down. If SiteMinder is active, the credentials from SiteMinder will override any such request.

The url can only be used once and must be used within 24 hours or it will expire.