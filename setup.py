from setuptools import setup, find_packages

setup(
    name="scheduler",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        'flask',
        'flask-sqlalchemy',
        'flask-session',
        'flask-mail',
        'flask-wtf',
        'psycopg2',
        'ldap3',
        'pydantic',
        'pydantic-settings'
    ]
)
