
# Installing / boot-strapping application

To use Python's virtual environments, run:

```sh
   $ python -m venv PATH_TO_VIRTUAL_ENV/NAME_OF_VIRTUAL_ENV
   $ source PATH_TO_VIRTUAL_ENV/NAME_OF_VIRTUAL_ENV/bin/activate
   $ python -m pip install -r requirements-venv.txt
```

to create, activate, and install all needed packages to that environment.

To use pipenv to create the environment that supports this application, run:

```sh
   $ pipenv install
```

which will use the contents of `Pipfile` to generate the `Pipfile.lock` manifest of versions and dependencies, after which pipenv will use this file to install and environment.  Like with virtual environments, this environment can be accessed by running the `activate` command within it.

Problems were encountered with finding `pipenv` and `pyenv` on Debian 12, so it is unclear how robust this option would be.

